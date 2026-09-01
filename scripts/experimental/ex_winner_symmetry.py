#!/usr/bin/env python3
"""去赢家口径的对称性检验：赢家取自谁，结论就偏向谁？

现行 §12.1 第 3 款的去赢家表把赢家定义为 `BASE` 臂锚定起点的前五名，再从全部臂统一剔除。
这对 `BASE` 是自伤、对挑战臂是顺风——只要挑战臂的赢家名单与 `BASE` 不同，被剔掉的就
主要是 `BASE` 的收益来源。本脚本按三组剔除集各跑一遍，量这个偏向有多大：

    A = BASE 前五（现行在册口径）        B = 挑战臂前五（镜像）       U = 两者并集（对称）

用法：ex_winner_symmetry.py <configs.txt> --challenger TW000 --out <file> [--workers N]
"""
import argparse, csv, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sweep_backtest_configs import (  # noqa: E402
    FIELDS, DEFAULT_STARTS, OUT_DIR, EX5_ANCHOR_START, EX5_FIELD, run_one, summary_tag)


def top5(label: str, since: str) -> list[str]:
    """读某臂锚定起点的前五赢家；该臂第一遍必须已跑过（summary 落在 OUT_DIR）。"""
    f = OUT_DIR / f"summary_{summary_tag(label, since)}.csv"
    rows = [r for r in csv.DictReader(f.open(encoding="utf-8")) if r["策略"].startswith("trend_")]
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
        for tag, codes in sets.items():
            fh.write(f"#SET|{tag}|{','.join(codes)}\n")
            # 标签带集合名，避免三组共用 summary_<label><since>ex5 而互相覆盖
            jobs = [(f"{tag}{label}", extra, s, ",".join(codes)) for label, extra in arms for s in starts]
            print(f"剔除集 {tag}（{len(codes)} 只）：{len(jobs)} 次运行，{args.workers} 并发", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for done, result in enumerate(pool.map(run_one, jobs), 1):
                    fh.write(result + "\n")
                    fh.flush()
                    if done % 25 == 0:
                        print(f"  {done}/{len(jobs)}", file=sys.stderr)


if __name__ == "__main__":
    main()
