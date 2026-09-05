#!/usr/bin/env python3
"""Count distinct RF5 events across all starts; overlapping paths are not samples."""
import concurrent.futures
import csv
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep
from whipsaw_swap_diag import Market, classify
from swap_chop_guard import ChopConfig, ChopGuard


def main():
    exp = ROOT / "data/experiments/exp_whipsaw_joint"
    groups, *_ = sweep.load_scan(exp / "sweep_r1.txt")
    def one(case):
        start, excluded = case
        group = "A" if excluded else "full"
        dest = exp / "census" / group / start
        dest.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "scripts/backtest_valuation_strategy.py"] + shlex.split(sweep.BASE)
        cmd += ["--since", start, "--until", "2026-08-28", "--swap-chop-mode", "repeat-flat",
                "--label-suffix", f"_wjc{group}{start.replace('-', '')}", "--out-dir", str(dest),
                "--trade-log", str(dest / "ledger.csv"), "--weak-block-log", str(dest / "blocked.csv")]
        if excluded:
            cmd += ["--exclude-codes", excluded]
        with (dest / "run.log").open("w") as fh:
            subprocess.run(cmd, cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT, check=True)
        with next(dest.glob("summary_*.csv")).open() as fh:
            result = list(csv.DictReader(fh))[-1]
        expected = groups[sweep.EX5_PREFIX if excluded else ""]["WJ_RF5"][start]
        for field in sweep.FIELDS:
            value = sweep._field_value(result, field)
            target = expected[field]
            assert value == target or abs(value - target) <= 0.00000051, (group, start, field, value, target)
        with (dest / "blocked.csv").open() as fh:
            blocked = [dict(group=group, start=start, **row) for row in csv.DictReader(fh)]
        with (dest / "ledger.csv").open() as fh:
            ledger = list(csv.DictReader(fh))
        for row in blocked:
            next_sale = next((t for t in ledger if t["action"] == "卖出" and t["security_code"] == row["source_code"]
                              and t["date"] >= row["exec_date"]), None)
            row.update(next_sale_date=next_sale["date"] if next_sale else "",
                       next_sale_price=next_sale["price"] if next_sale else "",
                       next_sale_reason=next_sale["reason"] if next_sale else "")
        return blocked
    tasks = [(s, excluded) for excluded in ("", "601088,002128,000933,000651,000338") for s in sweep.DEFAULT_STARTS]
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=28) as pool:
        for records in pool.map(one, tasks):
            rows.extend(records)
    mk = Market({r["source_code"] for r in rows} | {"002714"})
    for r in rows:
        label, f = classify(mk, r["source_code"], r["exec_date"])
        r.update(classification=label, return20=f[20], return60=f[60], min20=f["min20"])
    if rows:
        with (exp / "census_events.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    summary = {}
    for group in ("full", "A", "pooled"):
        chosen = [r for r in rows if group == "pooled" or r["group"] == group]
        unique = {(r["source_code"], r["exec_date"]): r for r in chosen}
        summary[group] = dict(path_events=len(chosen), distinct_dates_sources=len(unique),
                              distinct_sources=len({r["source_code"] for r in chosen}),
                              categories={k: sum(r["classification"] == k for r in unique.values())
                                          for k in ("假摔", "中间", "走坏", "无后续")})
    (exp / "census_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    shape_overlap(exp, rows, mk)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def shape_overlap(exp, rows, mk):
    unique = {(r["source_code"], r["signal_date"]): r["classification"] for r in rows}
    unique.update({("002714", d): "牧原" for d in ("2026-08-19", "2026-08-21", "2026-08-24")})
    guard = ChopGuard(ChopConfig("flat"), mk.raw, mk.ma, mk.actions)
    result = []
    for (code, day), category in sorted(unique.items(), key=lambda item: item[0][1]):
        i, ds = mk.idx(code, day), mk.days[code]
        closes = [guard.rebase(code, mk.raw[code][d], d, day) for d in ds[i - 19:i + 1]]
        ma, previous = mk.ma[code][day], mk.ma[code][ds[i - 5]]
        result.append(dict(code=code, signal_date=day, classification=category,
                           range20=max(closes) / min(closes) - 1, ma20_over_ma60=ma[20] / ma[60] - 1,
                           ma60_slope5=ma[60] / guard.rebase(code, previous[60], ds[i - 5], day) - 1))
    with (exp / "shape_overlap.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(result[0]))
        writer.writeheader()
        writer.writerows(result)


if __name__ == "__main__":
    main()
