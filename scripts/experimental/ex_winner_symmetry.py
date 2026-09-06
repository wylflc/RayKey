#!/usr/bin/env python3
"""去赢家口径的对称性检验：赢家取自谁，结论就偏向谁？

现行 §12.1 第 3 款的去赢家表把赢家定义为 `BASE` 臂锚定起点的前五名，再从全部臂统一剔除。
这对 `BASE` 是自伤、对挑战臂是顺风——只要挑战臂的赢家名单与 `BASE` 不同，被剔掉的就
主要是 `BASE` 的收益来源。本脚本按三组剔除集各跑一遍，量这个偏向有多大：

    A = BASE 前五（现行在册口径）        B = 挑战臂前五（镜像）       U = 两者并集（对称）

结果行标签 = `<集合>@<挑战臂><臂名>`（如 `EX5:A@SCBASE`），`#SET|A@SC|<代码>` 记集合；集合标签带挑战臂名，
不同实验的 A／B／U 行在扫描台账里不同名（OI-158：曾共用 `ABASE`／`BBASE`／`UBASE`，后一次运行顶掉前一次）。
赢家名单优先读 `data/backtest/summary_*.csv`，第一遍已归并进台账时改读 `scan_summaries.csv` 同标签行。

用法：ex_winner_symmetry.py <configs.txt> --challenger TW000 --out <file> [--workers N]
"""
import argparse, csv, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sweep_backtest_configs import (  # noqa: E402
    FIELDS, DEFAULT_STARTS, OUT_DIR, EX5_ANCHOR_START, EX5_FIELD, METRIC_VERSION, run_one, summary_tag)

LEDGER = OUT_DIR / "scan_summaries.csv"


def top5(label: str, since: str) -> list[str]:
    """读某臂锚定起点的前五赢家：先看 OUT_DIR 里的 summary，已被归并清掉时读现行台账的同标签行。"""
    tag = summary_tag(label, since)
    f = OUT_DIR / f"summary_{tag}.csv"
    if f.exists():
        rows = [r for r in csv.DictReader(f.open(encoding="utf-8")) if r["策略"].startswith("trend_")]
    else:
        rows = [r for r in csv.DictReader(LEDGER.open(encoding="utf-8"))
                if r.get("扫描标签") == tag and r["策略"].startswith("trend_")
                and (r.get("计量版本") or "") == METRIC_VERSION]
        if not rows:
            sys.exit(f"{label} 起点 {since} 的第一遍读数既不在 {OUT_DIR} 也不在 {LEDGER.name}（现行计量版本）——先跑第一遍")
    return [c for c in rows[-1][EX5_FIELD].split("/") if c]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("config", type=Path)
    ap.add_argument("--challenger", required=True, help="镜像剔除集取自哪条臂")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--starts", default="")
    args = ap.parse_args()

    starts = [s.strip() for s in args.starts.split(",") if s.strip()] or DEFAULT_STARTS
    anchor = EX5_ANCHOR_START if EX5_ANCHOR_START in starts else starts[0]
    arms = []
    for line in args.config.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            label, extra = line.split("|", 1)
            arms.append((label.strip(), extra))

    a, b = top5("BASE", anchor), top5(args.challenger, anchor)
    sets = {"A": a, "B": b, "U": sorted(set(a) | set(b))}
    print(f"锚定起点 {anchor}\n  A(BASE 前五)      = {','.join(a)}\n"
          f"  B({args.challenger} 前五)  = {','.join(b)}\n  U(并集 {len(sets['U'])} 只)     = {','.join(sets['U'])}\n"
          f"  仅 BASE 独有 = {','.join(sorted(set(a)-set(b))) or '—'}；"
          f"仅 {args.challenger} 独有 = {','.join(sorted(set(b)-set(a))) or '—'}", file=sys.stderr)

    with args.out.open("w", encoding="utf-8") as fh:
        for name, codes in sets.items():
            # 标签 = 集合名@挑战臂＋臂名：三组之间、以及不同挑战臂的实验之间都不共用 summary／台账标签
            tag = f"{name}@{args.challenger}"
            fh.write(f"#SET|{tag}|{','.join(codes)}\n")
            jobs = [(f"{tag}{label}", extra, s, ",".join(codes)) for label, extra in arms for s in starts]
            print(f"剔除集 {name}（{len(codes)} 只）：{len(jobs)} 次运行，{args.workers} 并发", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for done, result in enumerate(pool.map(run_one, jobs), 1):
                    fh.write(result + "\n")
                    fh.flush()
                    if done % 25 == 0:
                        print(f"  {done}/{len(jobs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
