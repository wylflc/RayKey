#!/usr/bin/env python3
"""Run the registered joint whipsaw experiment on allocated SLURM resources."""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep


def preserve_summaries(exp, phase):
    groups, orders, failed, note, version, fields = sweep.load_scan(exp / f"sweep_{phase}.txt")
    destination = exp / "summaries" / phase
    destination.mkdir(parents=True, exist_ok=True)
    for group, arms in groups.items():
        for arm, starts in arms.items():
            for start in starts:
                tag = sweep.summary_tag(arm, start, "ex" if group else "")
                original = sweep.OUT_DIR / f"summary_{tag}.csv"
                # Batch prefix prevents old BASE keys from overwriting historical ledger rows.
                shutil.copyfile(original, destination / f"summary_WJ{phase}20260906_{tag}.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase")
    ap.add_argument("--workers", type=int, default=60)
    ap.add_argument("--artifacts-only", action="store_true")
    ap.add_argument("--skip-artifacts", action="store_true")
    args = ap.parse_args()
    exp = ROOT / "data/experiments/exp_whipsaw_joint"
    cfg = exp / "configs" / f"{args.phase}.txt"
    if not args.artifacts_only:
        with (exp / f"report_{args.phase}.txt").open("w") as out:
            subprocess.run([sys.executable, "scripts/sweep_backtest_configs.py", str(cfg),
                            "--out", str(exp / f"sweep_{args.phase}.txt"), "--workers", str(args.workers),
                            "--title", f"MA20联合条件续研 {args.phase}"], cwd=ROOT, stdout=out, check=True)
        groups, orders, failed, note, version, fields = sweep.load_scan(exp / f"sweep_{args.phase}.txt")
        assert not any(failed.values()), failed
        for group in ("", sweep.EX5_PREFIX):
            assert groups[group], f"missing group {group}"
            assert all(len(x) == len(sweep.DEFAULT_STARTS) for x in groups[group].values())
        preserve_summaries(exp, args.phase)
    if args.skip_artifacts:
        return
    cases = []
    for line in cfg.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        label, extra = map(str.strip, line.split("|", 1))
        cases.append((label, extra))

    def run_case(case):
        label, extra = case
        dest = exp / args.phase / "bt2011" / label
        dest.mkdir(parents=True, exist_ok=True)
        cmd = ([sys.executable, "scripts/backtest_valuation_strategy.py"] + shlex.split(sweep.BASE)
               + ["--since", "2011-11-01", "--label-suffix", f"_wj{args.phase}_{label}"]
               + shlex.split(extra) + ["--out-dir", str(dest), "--artifacts",
                  "--trade-log", str(dest / "ledger.csv"), "--weak-block-log", str(dest / "blocked.csv"),
                  "--candidate-log", str(dest / "candidates.csv")])
        with (dest / "run.log").open("w") as out:
            subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)
        return label

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, args.workers)) as pool:
        for label in pool.map(run_case, cases):
            print(f"artifacts complete: {args.phase}/{label}", flush=True)
    if args.phase == "r1":
        reference = next((ROOT / "data/experiments/exp_whipsaw_swap/bt2011/BASE").glob("summary_*.csv"))
        current = next((exp / "r1/bt2011/BASE").glob("summary_*.csv"))
        def read(path):
            with path.open() as fh:
                return [r for r in csv.DictReader(fh) if r["策略"].startswith("trend_")][-1]
        old, new = read(reference), read(current)
        diff = {k: [v, new.get(k)] for k, v in old.items() if k != "策略" and new.get(k) != v}
        result = dict(columns=[len(old), len(new)], differences=diff)
        (exp / "base_identity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        assert not diff, result


if __name__ == "__main__":
    main()
