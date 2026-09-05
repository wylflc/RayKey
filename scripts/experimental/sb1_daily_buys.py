#!/usr/bin/env python3
"""SB1 × 每日买入笔数；复用现行 BASE、扫描器与标准报表，隔离本轮 summary。"""
from __future__ import annotations

import argparse
import collections
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import csv
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep

EXP = ROOT / "data/experiments/exp_sb1_daily_buys"
PANEL = ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv"


def subset(source, target, codes):
    """流式保存原始行字节，记录全文件 SHA256 与代码/日期覆盖。"""
    digest = hashlib.sha256()
    counts = collections.Counter()
    dates = collections.Counter()
    with source.open("rb") as src, target.open("wb") as out:
        header = next(src)
        assert header.startswith(b"security_code,date,"), source
        digest.update(header)
        out.write(header)
        for line in src:
            digest.update(line)
            code, date, _ = line.split(b",", 2)
            if code in codes:
                out.write(line)
                counts[code.decode()] += 1
                dates[date.decode()] += 1
    return dict(source=str(source.relative_to(ROOT)), sha256=digest.hexdigest(),
                rows=sum(counts.values()), codes=len(counts), first=min(dates), last=max(dates),
                last_day_rows=dates[max(dates)], subset=str(target.relative_to(ROOT)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=60)
    args = ap.parse_args()
    EXP.mkdir(parents=True, exist_ok=True)
    sweep.OUT_DIR = EXP / "summaries"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    with PANEL.open(encoding="utf-8-sig") as fh:
        codes = {r["security_code"].zfill(6).encode() for r in csv.DictReader(fh)}
    manifest = {"base": sweep.BASE, "starts": sweep.DEFAULT_STARTS,
                "engine_sha256": hashlib.sha256((ROOT / "scripts/backtest_valuation_strategy.py").read_bytes()).hexdigest(),
                "panel_sha256": hashlib.sha256(PANEL.read_bytes()).hexdigest(), "states": []}
    for side, name in (("cand", "adopted"), ("hold", "hold")):
        print(f"准备 {side} 面板子集", flush=True)
        manifest["states"].append(subset(ROOT / f"data/processed/a_share_daily_states_{name}.csv",
                                        EXP / f"states_{side}_sub.csv", codes))
    price_ends = collections.Counter()
    for code in sorted(codes):
        path = ROOT / f"data/raw/ohlcv/{code.decode()}.csv"
        if not path.exists():
            price_ends["missing"] += 1
            continue
        with path.open("rb") as fh:
            fh.seek(max(0, path.stat().st_size - 4096))
            price_ends[fh.read().splitlines()[-1].split(b",", 1)[0].decode()] += 1
    manifest["ohlcv_last_dates"] = dict(sorted(price_ends.items()))
    (EXP / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    common = f"--out-dir {shlex.quote(str(sweep.OUT_DIR))}"
    sub = (f"--daily-states {EXP}/states_cand_sub.csv "
           f"--hold-states {EXP}/states_hold_sub.csv")
    arms = [("BASE", common), ("SUBSET_CHECK", f"{common} {sub}")]
    arms += [("SB1", f"{common} {sub} --swap-source-block 1")]
    for cap in range(1, 7):
        arms += [(f"BUY{cap}", f"{common} {sub} --max-daily-buys {cap}"),
                 (f"SB1_BUY{cap}", f"{common} {sub} --swap-source-block 1 --max-daily-buys {cap}")]
    (EXP / "configs.txt").write_text("\n".join(f"{label}|{extra}" for label, extra in arms) + "\n", encoding="utf-8")
    results = {}
    sweep_file = EXP / "sweep.txt"
    with sweep_file.open("w", encoding="utf-8") as out:
        for excluded in (False, True):
            winners = ""
            if excluded:
                anchor, winners = sweep.read_top5_winners(sweep.DEFAULT_STARTS)
                assert winners, "missing BASE top five winners"
                out.write(f"#EX5|{anchor}|{winners}\n")
                manifest["excluded_A"] = winners.split(",")
            jobs = [(label, extra, start, winners) for label, extra in arms for start in sweep.DEFAULT_STARTS]
            print(f"{'去赢家' if excluded else '全样本'}：{len(jobs)} 次，{args.workers} 并发", flush=True)
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for i, line in enumerate(pool.map(sweep.run_one, jobs), 1):
                    out.write(line + "\n")
                    out.flush()
                    parts = line.split("|")
                    if len(parts) != 2 + len(sweep.FIELDS):
                        raise RuntimeError(f"backtest failed: {line}")
                    results[(parts[0], parts[1])] = parts[2:]
                    if i % 15 == 0:
                        print(f"  {i}/{len(jobs)}", flush=True)
            prefix = sweep.EX5_PREFIX if excluded else ""
            for start in sweep.DEFAULT_STARTS:
                assert results[(prefix + "BASE", start)] == results[(prefix + "SUBSET_CHECK", start)], start
    manifest["subset_equivalence"] = "28/28 paths: all sweep fields identical"
    (EXP / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (EXP / "report.txt").open("w", encoding="utf-8") as fh, redirect_stdout(fh):
        sweep.report(sweep_file, "SB1 × 每日买入笔数（2026-09-05）")
    print("全样本与去赢家完成，开始八臂 2011-11-01 流水核验", flush=True)
    selected = {"BASE", "SB1", "BUY1", "BUY3", "BUY5", "SB1_BUY1", "SB1_BUY3", "SB1_BUY5"}
    artifact_dir = EXP / "artifacts"
    artifact_dir.mkdir(exist_ok=True)

    def diagnostic(arm):
        label, extra = arm
        cmd = ([sys.executable, str(ROOT / "scripts/backtest_valuation_strategy.py")]
               + shlex.split(sweep.BASE) + shlex.split(extra)
               + ["--since", "2011-11-01", "--artifacts", "--out-dir", str(artifact_dir),
                  "--label-suffix", f"_daily_{label}", "--trade-log", str(EXP / f"trades_{label}.csv"),
                  "--candidate-log", str(EXP / f"cands_{label}.csv")])
        with (EXP / f"diag_{label}.txt").open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        with (EXP / f"trades_{label}.csv").open(encoding="utf-8-sig") as fh:
            counts = collections.Counter(r["date"] for r in csv.DictReader(fh) if r["action"] == "买入")
        if "BUY" in label:
            assert max(counts.values(), default=0) <= int(label[-1]), label
        return label, dict(buys=sum(counts.values()), buying_days=len(counts),
                           max_buys_per_day=max(counts.values(), default=0),
                           days_by_buy_count=dict(sorted(collections.Counter(counts.values()).items())))

    with ThreadPoolExecutor(max_workers=min(8, args.workers)) as pool:
        audit = dict(pool.map(diagnostic, [arm for arm in arms if arm[0] in selected]))
    (EXP / "buy_count_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("完成：标准表、28 路径子集等价、八臂实际成交笔数核验均通过", flush=True)


if __name__ == "__main__":
    main()
