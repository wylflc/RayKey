#!/usr/bin/env python3
"""Audit the single valuation change and archive small reproducible experiment evidence."""
from __future__ import annotations

import argparse
import collections
import csv
from datetime import datetime, timezone
from itertools import zip_longest
import json
import statistics
from types import SimpleNamespace

from trough_guard_review import EXP, ROOT, save_json
import clean_derived_artifacts as archive
import sweep_backtest_configs as sweep
from divspread_names import is_divspread_financial
from workflow_decision_log import append_decision_log, DEFAULT_DECISION_LOG, WORKFLOW_VERSION
from dose_table import load
from backtest_valuation_strategy import max_drawdown, rolling_windows
from trough_guard_checks import input_stamp


def bands():
    evidence = {}
    examples = []
    for side in ("cand", "b2"):
        count = collections.Counter()
        moves = []
        changed_codes = set()
        with (EXP / f"on/bands_{side}.csv").open(encoding="utf-8-sig") as a, \
                (EXP / f"off/bands_{side}.csv").open(encoding="utf-8-sig") as b:
            for on, off in zip_longest(csv.DictReader(a), csv.DictReader(b)):
                assert on is not None and off is not None
                for key in ("security_code", "report_date", "available_at", "peak_weight", "growth_trust", "ttm_factor"):
                    assert on[key] == off[key], (side, on["security_code"], on["report_date"], key)
                count["all_rows"] += 1
                assert float(off["trough_weight"] or 0) == 0
                if is_divspread_financial(on["security_code"], on["security_name"]):
                    count["financial_rows_overridden_by_divspread"] += 1
                    continue
                if on["status"] != off["status"]:
                    count["status_changed"] += 1
                if on["status"] != "ok" or off["status"] != "ok":
                    continue
                count["both_ok_nonfinancial"] += 1
                v0, v1 = float(on["intrinsic_value"]), float(off["intrinsic_value"])
                if float(on["trough_weight"] or 0) > 0:
                    count["trough_triggered"] += 1
                if v0 != v1:
                    assert float(on["trough_weight"] or 0) > 0
                    count["value_changed"] += 1
                    count["value_down" if v1 < v0 else "value_up"] += 1
                    moves.append(v1 / v0 - 1)
                    changed_codes.add(on["security_code"])
                    if side == "cand" and (on["security_code"], on["report_date"]) in {
                            ("000869", "2026-06-30"), ("002466", "2024-12-31"), ("600309", "2025-12-31")}:
                        examples.append(dict(code=on["security_code"], name=on["security_name"],
                                             report_date=on["report_date"], available_at=on["available_at"],
                                             on_v=v0, off_v=v1, trough_weight=on["trough_weight"]))
        evidence[side] = dict(count, changed_codes=len(changed_codes), changed_value_median=statistics.median(moves),
                              peak_trust_ttm_unchanged=True, all_off_trough_weights_zero=True)
    evidence["examples"] = examples
    save_json("band_audit.json", evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))


def archive_results():
    assert (EXP / "paired_metrics.csv").exists(), "finish checks before archiving"
    full, ex, _ = load(EXP / "sweep.txt")
    previous, previous_ex, _ = load(ROOT / "data/processed/experiments/exp_sb1_daily_buys/sweep.txt")
    for group, old in ((full, previous), (ex, previous_ex)):
        assert group["BASE"] == old["BASE"]
        for k in range(1, 7):
            assert group[f"ON_BUY{k}"] == old[f"BUY{k}"]
    # Archive the just-completed run's provenance; subsequent resumes must match it.
    stamp = input_stamp()
    if (EXP / "checks_inputs.json").exists():
        assert json.loads((EXP / "checks_inputs.json").read_text()) == stamp
    save_json("checks_inputs.json", stamp)
    windows = []
    drawdowns = {}
    for label in ("BASE", "OFF", "OFF_M13", "OFF_BUY1", "OFF_BUY3", "OFF_BUY5"):
        path = next((EXP / "artifacts").glob(f"*_trough_{label}_equity.csv"))
        with path.open(encoding="utf-8") as fh:
            curve = [(r["date"], float(r["net_equity"])) for r in csv.DictReader(fh)]
        drawdowns[label] = max_drawdown(curve)
        windows += [dict(arm=label, **r) for r in rolling_windows(curve, 5)]
    with (EXP / "rolling_windows_2011.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(windows[0]))
        writer.writeheader()
        writer.writerows(windows)
    save_json("drawdown_2011.json", drawdowns)
    entries = [SimpleNamespace(name="summary_TROUGH20260905_" + p.name.removeprefix("summary_"), path=str(p))
               for p in (EXP / "summaries").glob("summary_*.csv")]
    assert len(entries) == 756
    rows, columns = archive.merge_summaries(entries)
    with archive.MERGED.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    stamp = "trough_guard_review_20260905"
    with DEFAULT_DECISION_LOG.open(encoding="utf-8-sig") as fh:
        recorded = any(r.get("run_id") == stamp for r in csv.DictReader(fh))
    if not recorded:
        append_decision_log(DEFAULT_DECISION_LOG, [{
            "logged_at_utc": datetime.now(timezone.utc).isoformat(), "workflow_stage": "backtest", "run_id": stamp,
            "as_of": "2026-09-05", "decision_type": "strategy_experiment",
            "decision_result": "research_complete_no_production_change",
            "summary_reason": "定位历史GE_TROUGHOFF；新建带、27臂双表与截止日/赢家敏感性核验完成，生产未改；结论见报告。",
            "input_files": "data/processed/experiments/exp_trough_guard_review/manifest.json",
            "output_file": "docs/trough_guard_review.zh.md",
            "operator_or_script": "scripts/experimental/trough_guard_evidence.py", "workflow_version": WORKFLOW_VERSION,
        }])
    print(f"Archived {len(entries)} main summaries; BASE and ON_BUY1..6 reproduce 196 prior paths.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("bands", "archive"))
    args = ap.parse_args()
    bands() if args.stage == "bands" else archive_results()
