#!/usr/bin/env python3
"""Existing workflow signal checks for the fixed RF5 comparison."""
import concurrent.futures
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    exp = ROOT / "data/experiments/exp_whipsaw_joint"
    states = "data/processed/a_share_daily_states_adopted.csv"
    hold = "data/processed/a_share_daily_states_hold.csv"
    panel = "data/processed/pit_attention/panel_moat_bank_v6b.csv"
    tasks = []
    for label in ("BASE", "WJ_RF5"):
        folder = exp / "r2/bt2011" / label
        logs = ["--candidate-log", str(folder / "candidates.csv"), "--trade-log", str(folder / "ledger.csv")]
        tasks.append((f"signal_{label}", ["scripts/experimental/selection_edge_audit.py"] + logs))
        for tol in (0.04, 0.10, 0.15):
            tasks.append((f"swap_{label}_tol{tol}", ["scripts/experimental/swap_regime_control.py"] + logs
                          + ["--states", states, "--hold-states", hold, "--panel", panel, "--tol", str(tol)]))
    # PV panel inputs are identical in both arms; one computation serves both sides.
    tasks.append(("signal_panel_shared", ["scripts/experimental/panel_tier_forward.py", "--states", states,
                                         "--panel", panel, "--since", "2011-11-01"]))
    def one(item):
        label, args = item
        with (exp / f"{label}.txt").open("w") as out:
            subprocess.run([sys.executable] + args, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, check=True)
        return label
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for label in pool.map(one, tasks):
            print(f"completed {label}", flush=True)
    paired_signal_report(exp)


def paired_signal_report(exp):
    # Capture the existing audit's daily statistics, then pair the two arms on common days.
    # Subtracting their separately calculated medians would mix different day cohorts.
    import selection_edge_audit as audit
    original, argv = audit.print_block, sys.argv
    captured = {}
    try:
        for label in ("BASE", "WJ_RF5"):
            results = []
            audit.print_block = lambda title, result, note="": results.append(result)
            folder = exp / "r2/bt2011" / label
            sys.argv = ["selection_edge_audit.py", "--candidate-log", str(folder / "candidates.csv"),
                        "--trade-log", str(folder / "ledger.csv")]
            with redirect_stdout(io.StringIO()):
                audit.main()
            captured[label] = results
    finally:
        audit.print_block, sys.argv = original, argv
    daily, summary = [], {}
    for index, name in enumerate(("selection", "swap_direction")):
        base, arm = (dict(zip(captured[label][index]["days"], captured[label][index]["diffs"]))
                     for label in ("BASE", "WJ_RF5"))
        common = sorted(set(base) & set(arm))
        deltas = [arm[d] - base[d] for d in common]
        yearly = {y: statistics.median(arm[d] - base[d] for d in common if d.startswith(y))
                  for y in sorted({d[:4] for d in common})}
        summary[name] = dict(common_days=len(common), paired_median=statistics.median(deltas),
                             positive_days=sum(x > 0 for x in deltas), changed_days=sum(abs(x) > 1e-12 for x in deltas),
                             positive_years=sum(x > 0 for x in yearly.values()), year_count=len(yearly), yearly=yearly)
        daily += [dict(metric=name, date=d, base=base[d], candidate=arm[d], delta=arm[d] - base[d]) for d in common]
    with (exp / "signal_paired_daily.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(daily[0]))
        writer.writeheader()
        writer.writerows(daily)
    (exp / "signal_paired_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
