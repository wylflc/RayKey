#!/usr/bin/env python3
"""SB1 买入上限实验的统一截止日与赢家并集核验；只读取已登记配置。"""
from __future__ import annotations

import argparse
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
from dose_table import load, verdict
from sb1_daily_buys import EXP


def top5(directory, label):
    path = directory / f"summary_{sweep.summary_tag(label, sweep.EX5_ANCHOR_START)}.csv"
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return set(rows[-1][sweep.EX5_FIELD].split("/"))


def run_pass(arms, excluded, workers, out):
    jobs = [(label, extra, start, excluded) for label, extra in arms for start in sweep.DEFAULT_STARTS]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, line in enumerate(pool.map(sweep.run_one, jobs), 1):
            if len(line.split("|")) != 2 + len(sweep.FIELDS):
                raise RuntimeError(line)
            out.write(line + "\n")
            out.flush()
            if i % 28 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--cutoff", default="2026-08-07")
    args = ap.parse_args()
    manifest = json.loads((EXP / "manifest.json").read_text())
    assert manifest.get("subset_equivalence"), "main sweep must finish first"
    assert hashlib.sha256((ROOT / "scripts/backtest_valuation_strategy.py").read_bytes()).hexdigest() == manifest["engine_sha256"]
    sweep.BASE = manifest["base"]
    original_dir = EXP / "summaries"
    arms = [tuple(line.split("|", 1)) for line in (EXP / "configs.txt").read_text().splitlines()
            if not line.startswith("SUBSET_CHECK|")]
    sweep.OUT_DIR = EXP / "checks_summaries"
    sweep.OUT_DIR.mkdir(exist_ok=True)
    common = (f" --out-dir {sweep.OUT_DIR} --daily-states {EXP}/states_cand_sub.csv"
              f" --hold-states {EXP}/states_hold_sub.csv")
    cutoff_arms = [(label, extra + common + f" --until {args.cutoff}") for label, extra in arms]
    cutoff_path = EXP / "sweep_cutoff.txt"
    print(f"统一截止 {args.cutoff}：{len(arms)} 臂 × 14 起点 × 两遍", flush=True)
    with cutoff_path.open("w", encoding="utf-8") as out:
        run_pass(cutoff_arms, "", args.workers, out)
        excluded = ",".join(sorted(top5(sweep.OUT_DIR, "BASE")))
        out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{excluded}\n")
        run_pass(cutoff_arms, excluded, args.workers, out)
    with (EXP / "report_cutoff.txt").open("w", encoding="utf-8") as out, redirect_stdout(out):
        sweep.report(cutoff_path, f"SB1 买入上限：统一截止 {args.cutoff}")

    all_rows, ex_rows, labels = load(EXP / "sweep.txt")
    candidates = [label for label in labels if label not in ("BASE", "SUBSET_CHECK")
                  and verdict(all_rows, ex_rows, label).startswith(("可采纳", "报用户裁定"))]
    sets = {}
    a = top5(original_dir, "BASE")
    original_lines = (EXP / "sweep.txt").read_text().splitlines()
    for label in candidates:
        b = top5(original_dir, label)
        union = a | b
        sets[label] = {"A": sorted(a), "B": sorted(b), "U": sorted(union)}
        path = EXP / f"sweep_union_{label}.txt"
        with path.open("w", encoding="utf-8") as out:
            for line in original_lines:
                if line.split("|", 1)[0] in ("BASE", label):
                    out.write(line + "\n")
            out.write(f"#EX5|{sweep.EX5_ANCHOR_START}|{','.join(sorted(union))}\n")
            if union == a:
                for line in original_lines:
                    if line.split("|", 1)[0] in ("EX5:BASE", f"EX5:{label}"):
                        out.write(line + "\n")
            else:
                print(f"{label} 赢家并集 {len(union)} 只", flush=True)
                union_arms = [(name, extra + common) for name, extra in arms if name in ("BASE", label)]
                run_pass(union_arms, ",".join(sorted(union)), args.workers, out)
        with (EXP / f"report_union_{label}.txt").open("w", encoding="utf-8") as out, redirect_stdout(out):
            sweep.report(path, f"{label} 对 BASE：统一剔除赢家并集 U")
    (EXP / "union_sets.json").write_text(json.dumps(sets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 相邻档位 2 笔初筛较强，补齐与八个用户指定臂同口径的流水与贡献归因。
    for label, extra in arms:
        if label not in ("BUY2", "SB1_BUY2"):
            continue
        cmd = ([sys.executable, str(ROOT / "scripts/backtest_valuation_strategy.py")]
               + shlex.split(sweep.BASE) + shlex.split(extra)
               + ["--since", "2011-11-01", "--artifacts", "--out-dir", str(EXP / "artifacts"),
                  "--label-suffix", f"_daily_{label}", "--trade-log", str(EXP / f"trades_{label}.csv"),
                  "--candidate-log", str(EXP / f"cands_{label}.csv")])
        with (EXP / f"diag_{label}.txt").open("w", encoding="utf-8") as out:
            subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)
    print("统一截止日与初筛通过臂的赢家并集核验完成", flush=True)


if __name__ == "__main__":
    main()
