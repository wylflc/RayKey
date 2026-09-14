#!/usr/bin/env python3
"""Offline audit observations; temporary fixtures never touch production outputs.

Run from any directory. Results describe the audited behavior, not desired behavior.
This is an audit reproducer, not a replacement strategy test suite.
"""
from __future__ import annotations

import contextlib
import copy
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_valuation_strategy as bt
import screen_daily_volume_price_signals as scan
import track_holdings_daily as tracker


def row(code="000001", price=100.0, pv=0.5):
    return dict(security_code=code, security_name="synthetic_" + code,
                close=price, ma20=price * .95, ma60=price * .9,
                model_pv=pv, hold_pv=pv, signal_state="ok",
                trade_date="2026-09-14", quality_score="70")


def holding(shares=1000.0, cost=95.0):
    return dict(name="synthetic_holding", shares=shares, cost=cost, stop=None)


def plan(rows, holdings=None, members=None, funds=100000.0, **kwargs):
    return scan.section93_execution_plan(
        rows, 1e6, funds, holdings or {}, set(), set(), members, **kwargs)


def buy_summary(result):
    return [{k: p[k] for k in ("security_code", "shares", "amount")}
            for p in result["plan"]]


def fake_main(rows, missing_bands=False):
    with tempfile.TemporaryDirectory(prefix="workflow_audit_") as directory:
        p = Path(directory)
        bands = p / "bands.csv"
        if not missing_bands:
            bands.write_text("security_code\n")
        buys = p / "buys.csv"
        buys.write_text("OLD_PLAN_SENTINEL\n")
        args = ["scan", "--as-of", "2026-09-14", "--since", "",
                "--input", str(p / "pool.csv"), "--model-bands", str(bands),
                "--hold-bands", str(bands), "--nav", "1000000", "--funds", "200000",
                "--rf", ".02", "--review-queue", str(p / "missing_queue.csv"),
                "--triage", str(p / "missing_triage.csv"),
                "--holdings", str(p / "missing_holdings.csv"),
                "--output-csv", str(p / "quotes.csv"), "--plan-out", str(buys),
                "--sell-out", str(p / "sells.csv"),
                "--cooldown-state", str(p / "cooldown.csv")]
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", args))
            stack.enter_context(patch.object(scan, "load_csv", return_value=[]))
            stack.enter_context(patch.object(scan, "scan", return_value=copy.deepcopy(rows)))
            stack.enter_context(patch.object(scan, "load_model_bands", return_value={}))
            stack.enter_context(patch.object(scan, "attach_model_pv"))
            stack.enter_context(patch.object(scan, "log_scan_decisions"))
            stack.enter_context(patch.object(scan, "load_tactical_gate_codes", return_value=set()))
            stack.enter_context(patch.object(scan, "equity_bond_signal", return_value=(None, None)))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            code = scan.main()
        cd = p / "cooldown.csv"
        return dict(exit_code=code,
                    old_plan_retained=buys.read_text() == "OLD_PLAN_SENTINEL\n",
                    buy_plan=buys.read_text(),
                    cooldown=cd.read_text() if cd.exists() else None)


def observe():
    result = {}
    scan.CLOSE_SERIES.clear()
    # Same signal-day equity, but execution-day marks change tranche size.
    states = {d: [("000001", price, 40., price / 40.)] for d, price in
              [("2024-01-02", 10.), ("2024-01-03", 10.), ("2024-01-04", 12.)]}
    prices = {"000001": {d: rs[0][1] for d, rs in states.items()}}
    mas = {"000001": {d: {20: 8., 60: 7.} for d in states}}
    ledger = []
    with patch.object(bt, "trade_fee", return_value=0.), patch.object(bt, "DELISTED_LAST", {}):
        bt.run("trend", .05, states, prices, {}, mas, min(states), max(states), 1e6,
               width=-.0454, trend_tranche=True, trend_ma=(20, 60),
               exec_delay=1, exec_price="close", stop_ma=60,
               stop_line="min_entry_current", entry_below_ma60="ma60_stop",
               addon_trend="ma-only", gain_sell=1.1, gain_sell_mode="ungated",
               lot_size=100, ledger=ledger)
    result["tranche_date"] = dict(
        signal_day_nav=1e6, execution_day_nav_before_trade=1010000.,
        documented_tranche=50000., actual_engine_tranche=50500.,
        documented_shares_at_execution_price=4100,
        engine_ledger=ledger,
        note="Synthetic prices; fees disabled to isolate NAV timing, not a full BASE replay.")

    # A provider returning a valid but old final candle is accepted by the scanner.
    days = [date(2026, 6, 1) + timedelta(days=i) for i in range(103)]
    days = [d for d in days if d.weekday() < 5][-60:]
    candles = [dict(date=d.isoformat(), close=100. + i, open=100. + i,
                    volume=1000., amount=100000.) for i, d in enumerate(days)]
    with patch.object(scan, "fetch_daily_rows", return_value=("synthetic", copy.deepcopy(candles))):
        r = scan.scan_one(dict(security_code="000001", security_name="synthetic"),
                          "2026-09-14", 1.)
        r["model_pv"] = .5
        result["stale_quote"] = dict(requested_date="2026-09-14",
                                    quote_date=r["trade_date"], state=r["signal_state"],
                                    plan=buy_summary(plan([r])))
    with patch.object(tracker, "fetch_daily_rows", return_value=("synthetic", copy.deepcopy(candles))):
        result["stale_quote"]["tracker_close"] = tracker.fetch_raw_close(
            "000001", date(2026, 9, 14), 1.)[0]

    result["non_member_buy"] = buy_summary(plan([row()], members=set()))
    r = plan([row()], {"000001": holding()}, members=set(), funds=0.)
    result["exit_and_rebuy"] = dict(
        sells=[{k: s[k] for k in ("rule", "sell_shares")} for s in r["sells"]],
        buys=buy_summary(r))

    counters = {}
    first = plan([row(price=1500.)], members={"000001"}, funds=0., counters=counters)
    after_first = dict(counters)
    second = plan([row(price=1500.)], members={"000001"}, funds=200000., counters=counters)
    result["unfunded_cooldown"] = dict(
        first_buys=buy_summary(first), first_counters=after_first,
        next_funded_buys=buy_summary(second), next_counters=dict(counters))

    r = plan([row()], {"000002": holding(shares=10000.)},
             members={"000001", "000002"}, exposure_cap=.3, cap_cash=500000.)
    result["missing_holding_cap"] = dict(
        missing=r["missing_holdings"], marked_stock_before=r["eb_stock_before"],
        marked_stock_after=r["eb_stock_after"], buys=buy_summary(r))

    result["failure_publishes"] = fake_main([
        row(price=1500.), dict(security_code="000002", security_name="failed",
                              signal_state="data_error", trade_date="2026-09-14")])
    result["missing_bands_success"] = fake_main([row()], missing_bands=True)
    result["missing_queue_success"] = fake_main([row()])

    # Tracker revives an absent/rejected industrial model through the pool display band.
    with tempfile.TemporaryDirectory(prefix="workflow_audit_tracker_") as directory:
        hp = Path(directory) / "holdings.csv"
        hp.write_text("security_code,security_name,current_shares,cost_basis,entry_stop_price\n"
                      "000001,synthetic_industrial,100,100,\n")
        p = {"000001": dict(fair_price_low="160", fair_price_high="200")}
        with patch.object(tracker, "MODEL_BANDS", {}), patch.object(tracker, "CAND_BANDS", {}), \
             patch.object(tracker, "load_pool", return_value=p), \
             patch.object(tracker, "is_bank", return_value=False), \
             patch.object(tracker, "resolve_prices", return_value=({"000001": 100.}, {}, {}, "收盘")):
            tracked = tracker.track(hp, hp, date(2026, 9, 14), "", 1.)[0]
        result["tracker_missing_model_fallback"] = dict(pv=tracked["pv"], action=tracked["action"])
    return result


def current_snapshot():
    import collections
    import build_company_dossier_readmes as renderer

    def load(path):
        with path.open(encoding="utf-8-sig") as handle:
            return {r["security_code"].zfill(6): r for r in csv.DictReader(handle)}

    p = ROOT / "data/processed"
    pool = load(p / "a_share_core_valuation_pool.csv")
    triage = load(p / "a_share_attention_triage.csv")
    candidates = load(p / "a_share_pool_model_bands_adopted.csv")
    holds = load(p / "a_share_pool_model_bands_hold.csv")
    quotes = load(p / "daily_buy_candidates.csv")
    tracking = load(p / "daily_holdings_tracking.csv")
    dossiers = load(renderer.DOSSIERS)
    tiers = load(renderer.TIERS)
    renderer.TRIAGE_CLASS.update({c: r.get("attention_class", "") for c, r in triage.items()})
    bands, _ = renderer.latest_model_bands(renderer.ADOPTED, renderer.MIN_AVAILABLE)
    drift, outside_price_section = [], []
    for code, r in dossiers.items():
        old = (ROOT / r["dossier_dir"] / "README.md").read_text()
        new, _ = renderer.render(r, pool, bands, tiers)
        if old != new:
            drift.append(code)
            if old.split("## 八、现价隐含了什么")[0] != new.split("## 八、现价隐含了什么")[0]:
                outside_price_section.append(code)
    worth = {c for c, r in triage.items() if r.get("attention_class") == "worth_attention"}
    return dict(
        worth_count=len(worth), pool_count=len(pool),
        worth_missing_from_pool=sorted(worth - pool.keys()),
        pool_outside_worth=sorted(pool.keys() - worth),
        candidate_hold_pool_same_codes=candidates.keys() == holds.keys() == pool.keys(),
        hold_values_below_candidate=[c for c in holds if float(holds[c]["intrinsic_value"]) + 1e-6
                                     < float(candidates[c]["intrinsic_value"])],
        quote_dates=dict(collections.Counter(r.get("trade_date", "") for r in quotes.values())),
        quote_states=dict(collections.Counter(r.get("signal_state", "") for r in quotes.values())),
        held_close_or_ma60_mismatch=[c for c, r in tracking.items()
            if abs(float(r["close"]) - float(quotes[c]["close"])) > .00011
            or abs(float(r["ma60"]) - float(quotes[c]["ma60"])) > .00011],
        held_count=len(tracking),
        pool_dossier_band_mismatch=[c for c, r in pool.items() if r.get("fair_price_low")
            and (abs(float(r["fair_price_low"]) - float(dossiers[c]["band_low"])) > .011
                 or abs(float(r["fair_price_high"]) - float(dossiers[c]["band_high"])) > .011)],
        dossier_count=len(dossiers), readme_drift_count=len(drift), readme_drift_codes=drift,
        readme_drift_outside_price_section=outside_price_section)


if __name__ == "__main__":
    observations = observe()
    observations["current_snapshot"] = current_snapshot()
    print(json.dumps(observations, ensure_ascii=False, indent=2))
