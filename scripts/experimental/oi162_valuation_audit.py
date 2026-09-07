#!/usr/bin/env python3
"""OI-162：使用已落盘的收盘价核验四个估值入口，按需修正跟踪与阅读版。"""
import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import build_a_share_core_valuation_pool as pool
import screen_daily_volume_price_signals as scan
import track_holdings_daily as tracker
from a_share_signal_dates import evidence_iso_for_signal
from pv_ratio import load_model_bands
from resolve_trade_valuation import trade_valuation
from workflow_decision_log import append_decision_log, WORKFLOW_VERSION


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    target = ROOT / "data/experiments/exp_oi162_valuation"
    target.mkdir(exist_ok=True)
    protected = [ROOT / "data/processed" / f for f in (
        "a_share_holdings.csv", "portfolio_account_snapshot.csv", "daily_entry_plan.csv", "daily_sell_plan.csv")]
    before = {str(p.relative_to(ROOT)): digest(p) for p in protected}
    rows = read(tracker.DEFAULT_OUTPUT_CSV)
    assert rows and all(r["as_of"] == args.as_of for r in rows)
    financial = [r for r in rows if scan.is_bank(r["security_name"], r["security_code"])]
    codes = {r["security_code"] for r in financial}
    prices = {r["security_code"]: float(r["close"]) for r in financial if r["close"]}
    mas = [{r["security_code"]: float(r[k]) for r in financial if r[k]} for k in ("ma20", "ma60")]
    evidence = evidence_iso_for_signal(args.as_of)
    candidate = load_model_bands(scan.DEFAULT_MODEL_BANDS, as_of=evidence)
    hold = load_model_bands(scan.DEFAULT_HOLD_BANDS, as_of=evidence)
    with patch.object(tracker, "resolve_prices", return_value=(prices, *mas, "收盘")):
        refreshed = tracker.track(tracker.DEFAULT_HOLDINGS, tracker.DEFAULT_VALUATION_POOL,
                                  date.fromisoformat(args.as_of), ",".join(sorted(codes)), 1)
    by_code = {r["security_code"]: r for r in refreshed}
    pool_rows = {r["security_code"]: r for r in read(tracker.DEFAULT_VALUATION_POOL)}
    pool.MODEL_BANDS = candidate
    pool.VALUATION_AS_OF = args.as_of
    scan_rows = {r["security_code"]: r for r in read(ROOT / "data/processed/daily_buy_candidates.csv")}
    checks = []
    for previous in financial:
        code = previous["security_code"]
        current = by_code[code]
        cells = pool.display_cells(pool_rows[code], {"price": prices[code]})
        trade = trade_valuation(code, previous["security_name"], args.as_of, prices[code], candidate, hold)
        v = trade["candidate"]["intrinsic_value"]
        ratio = trade["candidate"]["pv"]
        assert current["pv"] == f"{ratio:.2f}"
        assert cells["pv"] == f"{ratio:.3f}"
        assert abs(float(current["fair_price_low"]) - v * .9) < .0001
        assert abs(float(scan_rows[code]["model_intrinsic_value"]) - v) < .0001
        assert abs(float(scan_rows[code]["model_pv"]) - ratio) < .0001
        checks.append({"security_code": code, "price": prices[code], "previous": previous,
                       "tracking": current, "reading": cells, "trade": trade, "scan_matches": True})
    # 使用文件中原有价格逐行调用阅读版单元格渲染器；保留价格时间与海外附表。
    md = pool.DEFAULT_OUTPUT_MD.read_text()
    lines = []
    reading_updates = []
    for line in md.splitlines():
        parts = [x.strip() for x in line.split("|")]
        if len(parts) == 12 and parts[1] in pool_rows and scan.is_bank(parts[2], parts[1]):
            try:
                price = float(parts[6])
            except ValueError:
                lines.append(line)
                continue
            cells = pool.display_cells(pool_rows[parts[1]], {"price": price})
            reading_updates.append({"security_code": parts[1], "before": line,
                                    "fair_value": cells["fair_value"], "pv": cells["pv"]})
            parts[7], parts[8] = cells["fair_value"], cells["pv"]
            line = "| " + " | ".join(parts[1:-1]) + " |"
        lines.append(line)
    assert codes <= {r["security_code"] for r in reading_updates}
    if args.apply:
        with tracker.DEFAULT_OUTPUT_CSV.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(by_code.get(r["security_code"], r) for r in rows)
        pool.DEFAULT_OUTPUT_MD.write_text("\n".join(lines) + "\n")
        records = []
        for row in refreshed:
            records.append({"logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "workflow_stage": "holdings_tracking", "run_id": f"oi162:{args.as_of}", "as_of": args.as_of,
                "security_code": row["security_code"], "security_name": row["security_name"],
                "decision_type": "daily_holdings_tracking", "decision_result": "OI-162 估值同源更正",
                "summary_reason": f"复用已落盘收盘价 {row['close']}；股利折现区间 {row['fair_price_low']}–{row['fair_price_high']}，P/V {row['pv']}；四入口核验一致。",
                "input_files": "data/processed/daily_buy_candidates.csv;data/reference/cost_of_equity_inputs.csv;data/raw/corporate_actions/a_share_corporate_actions.csv",
                "output_file": "data/processed/daily_holdings_tracking.csv;docs/000_a_share_core_valuation_pool.md",
                "operator_or_script": "oi162_valuation_audit.py", "workflow_version": WORKFLOW_VERSION,
                "decision_id": f"holdings_tracking:{args.as_of}:{row['security_code']}:oi162",
                "supersedes_decision_id": f"holdings_tracking:{args.as_of}:{row['security_code']}:01"})
        append_decision_log(tracker.DEFAULT_DECISION_LOG, records)
    assert before == {str(p.relative_to(ROOT)): digest(p) for p in protected}
    report = {"as_of": args.as_of, "applied": args.apply, "price_source": "existing dated scan/tracking CSV; no network refresh",
              "checks": checks, "reading_updates": reading_updates, "protected_files_unchanged": before}
    (target / ("verification.json" if args.apply else "preview.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Four valuation consumers agree for {len(checks)} holdings; {len(reading_updates)} financial reading rows; apply={args.apply}")


if __name__ == "__main__":
    main()
