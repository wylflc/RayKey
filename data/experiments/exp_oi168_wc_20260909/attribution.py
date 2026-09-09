"""Replay the already measured arms at both standard anchors for trade attribution.

No new parameters are tested. Per-path metrics must reproduce the frozen scan.
"""
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
from itertools import zip_longest
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP))
from build import fingerprint, save
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts/experimental"))
import sweep_backtest_configs as sw
from delta_attribution import load_contrib


def main():
    configs = dict(line.split("|", 1) for line in (EXP / "configs.txt").read_text().splitlines()
                   if line and not line.startswith("#"))
    with (EXP / "summary_rows.csv").open() as f:
        reference = {(r["group"], r["arm"], r["start"]): r for r in csv.DictReader(f)}
    exclude = json.loads((EXP / "winner_sets.json").read_text())["WCOPM15SEP09"]["A"]
    protected = {ROOT / p for p in json.loads((EXP / "scan_manifest.json").read_text())["inputs"]}
    protected |= {EXP / "attribution.py", EXP / "attribution_plan.md"}
    original = fingerprint(protected)
    save("attribution_manifest.json", {"started_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
         "job_id": os.environ.get("SLURM_JOB_ID"), "inputs": original, "paths": 24, "workers": 8})
    def replay(task):
        group, arm, start = task
        out = EXP / "attrib" / group / start / arm
        out.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "scripts/backtest_valuation_strategy.py", *shlex.split(sw.BASE),
               *shlex.split(configs[arm]), "--since", start, "--artifacts", "--out-dir", str(out),
               "--label-suffix", "_" + arm, "--trade-log", str(out / "ledger.csv")]
        if group == "A": cmd += ["--exclude-codes", ",".join(exclude)]
        with (out / "run.log").open("w") as f:
            subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
        with (out / ("summary_" + arm + ".csv")).open() as f:
            row = next(csv.DictReader(f))
        old = reference[task]
        for field in (*sw.FIELDS, "前五赢家", "首个净值日", "末次净值日"):
            assert row[field] == old[field], (task, field, row[field], old[field])
        return task, out
    tasks = [(g, a, s) for g in ("full", "A") for s in ("2009-11-01", "2011-11-01") for a in configs]
    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = dict(executor.map(replay, tasks))
    reports = []; code_rows = []; divergences = []
    pairs = [(a, "BASE") for a in configs if a != "BASE"] + [
        ("WCOPM15SEP09", "WCREPSEP09"), ("WCOPM15SEP09", "WCOPRAWSEP09"),
        ("WCOPM16SEP09", "WCOPM15SEP09")]
    for group in ("full", "A"):
        for start in ("2009-11-01", "2011-11-01"):
            for arm, base in pairs:
                bpath, apath = paths[group, base, start], paths[group, arm, start]
                bfile, afile = next(bpath.glob("*_trades.csv")), next(apath.glob("*_trades.csv"))
                b, b_rel = load_contrib(bfile); a, a_rel = load_contrib(afile)
                assert b_rel and a_rel
                delta = {c: a.get(c, 0) - b.get(c, 0) for c in set(a) | set(b)}
                ranked = sorted(delta, key=lambda c: (-abs(delta[c]), c))
                total = sum(delta.values()); gross = sum(abs(v) for v in delta.values())
                meta = dict(group=group, start=start, arm=arm, base=base)
                reports.append({**meta, "delta_contribution": total,
                    "delta_CAGR": float(reference[group, arm, start]["年化"]) - float(reference[group, base, start]["年化"]),
                    "top3_codes": "/".join(ranked[:3]),
                    "top3_net_share": sum(delta[c] for c in ranked[:3]) / total if abs(total) > 1e-6 else None,
                    "top3_gross_share": sum(abs(delta[c]) for c in ranked[:3]) / gross if gross else None})
                code_rows.extend({**meta, "rank": i, "security_code": c, "base_contribution": b.get(c, 0),
                                  "arm_contribution": a.get(c, 0), "delta_contribution": delta[c]}
                                 for i, c in enumerate(ranked, 1))
                with (EXP / "attrib" / f"{group}_{start}_{arm}_vs_{base}.txt").open("w") as f:
                    subprocess.run([sys.executable, "scripts/experimental/delta_attribution.py", "--base", str(bfile),
                                    "--arm", str(afile)], stdout=f, cwd=ROOT, check=True)
                with (bpath / "ledger.csv").open() as bf, (apath / "ledger.csv").open() as af:
                    for i, (br, ar) in enumerate(zip_longest(csv.DictReader(bf), csv.DictReader(af)), 1):
                        if br != ar:
                            divergences.append({**meta, "ledger_row": i, "base_trade": br, "arm_trade": ar})
                            break
    for name, rows in (("attribution_summary.csv", reports), ("attribution_codes.csv", code_rows)):
        with (EXP / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)
    save("first_trade_divergences.json", divergences)
    unchanged = fingerprint(protected) == original
    save("attribution_verification.json", {"paths_reproduced": len(paths), "metrics_per_path": len(sw.FIELDS),
         "inputs_unchanged": unchanged, "completed_beijing": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
         "scope": "Closed-cycle cumulative daily PnL / previous NAV; not an additive CAGR decomposition."})
    assert unchanged
    print("Attribution complete; 24 anchor paths reproduced.", flush=True)


if __name__ == "__main__":
    main()
