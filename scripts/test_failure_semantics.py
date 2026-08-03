#!/usr/bin/env python3
"""Regression tests for what the scripts do when things go *wrong*.

Run: ``python3 scripts/test_failure_semantics.py``

Why this file exists: as of 2026-08-03 the only test suite in the repo
(``test_validate_valuation_bands.py``) spent 9 of its 21 cases defending the
§6.5.6 growth-option mechanism — retired and *forbidden* since v2.00, with all
five of its columns empty across all 261 rows, so the guard had never fired
once. Meanwhile the failures that actually happen had no coverage at all:

* the quote feed returns nothing and the holdings tracker prints 「持有」
* the whole market fails to fetch and the scan still exits 0
* a decision-log row records a file the run never opened

All three are the same defect class — §15.2 第 3 条「静默失效」, a failure that
reads as a success. These tests lock the honest behaviour in.

No network, no fixtures on disk: every case drives a pure function.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import track_holdings_daily as tracker  # noqa: E402
from screen_daily_volume_price_signals import data_error_exit_code  # noqa: E402

HOLDING = {
    "security_code": "600519",
    "security_name": "贵州茅台",
    "current_shares": "100",
    "cost_basis": "1500",
    "stop_loss_price": "1400",
}
POOL_ROW = {
    "security_code": "600519",
    "quality_tier": "L1",
    "fair_price_low": "1600",
    "fair_price_high": "2000",
}


def run_tracker(price, *, stop="1400", pool=True, monkey_quotes=None):
    """Drive tracker.track() with the network stubbed out."""
    holding = dict(HOLDING, stop_loss_price=stop)
    quotes = monkey_quotes if monkey_quotes is not None else (
        {} if price is None else {"600519": {"price": price}}
    )

    real_fetch, real_load, real_open = tracker.fetch_spot_quotes, tracker.load_pool, Path.open

    class FakeFile:
        def __enter__(self):
            header = ",".join(holding)
            return iter([header, ",".join(str(holding[k]) for k in holding)])

        def __exit__(self, *a):
            return False

    tracker.fetch_spot_quotes = lambda *a, **k: quotes
    tracker.load_pool = lambda *a, **k: ({"600519": POOL_ROW} if pool else {})
    Path.open = lambda self, *a, **k: FakeFile()  # type: ignore[assignment]
    try:
        return tracker.track(Path("x.csv"), Path("y.csv"), date(2026, 8, 3), "", 8.0)[0]
    finally:
        tracker.fetch_spot_quotes, tracker.load_pool, Path.open = real_fetch, real_load, real_open


def case_no_quote_is_not_hold():
    """核心用例：取不到行情时动作必须是 `数据缺失`，绝不能是 `持有`。

    旧版落 `持有` 并在备注写「沿用上一交易日结论」，而脚本从不读上一日文件——
    一只已跌破割肉价的停牌股会显示为持有，在 Tier-0 规则上制造静默失效。
    """
    row = run_tracker(None)
    if row["action"] == "持有":
        return ["无行情却判 `持有` —— 正是本测试要拦的那个缺陷"]
    if row["action"] != "数据缺失":
        return [f"无行情时应判 `数据缺失`，实得 `{row['action']}`"]
    if "沿用上一交易日" in str(row.get("note", "")):
        return ["备注仍声称『沿用上一交易日结论』，但脚本并未读取上一日文件"]
    return []


def case_no_quote_never_claims_stop_checked():
    row = run_tracker(None)
    return [] if not row.get("stop_hit") else ["无行情却断言割肉未触及"]


def case_stop_breach_still_detected():
    row = run_tracker(1350.0)  # 1350 <= 1400 割肉价
    return [] if row["action"] == "割肉提醒" else [f"跌破割肉价应判 `割肉提醒`，实得 `{row['action']}`"]


def case_normal_day_is_hold():
    row = run_tracker(1800.0)  # 带内、未破割肉价
    return [] if row["action"] == "持有" else [f"正常日应判 `持有`，实得 `{row['action']}`"]


def case_all_rows_failed_is_not_success():
    """全市场取数失败必须非 0 退出——否则调度器与下游都看不出今天没扫成。"""
    rows = [{"signal_state": "data_error"} for _ in range(10)]
    code = data_error_exit_code(rows)
    return [] if code != 0 else ["全部 data_error 仍退出 0（静默成功）"]


def case_empty_scan_is_not_success():
    return [] if data_error_exit_code([]) != 0 else ["扫描 0 行仍退出 0"]


def case_isolated_failures_still_pass():
    """个别停牌是常态，不能因此判整批失败。"""
    rows = [{"signal_state": "data_error"}] + [{"signal_state": "buy_candidate"}] * 19
    code = data_error_exit_code(rows)
    return [] if code == 0 else [f"1/20 失败不应中断，实得退出码 {code}"]


def case_pool_provenance_uses_actual_path():
    """溯源列必须写实际读到的文件，不是模块默认常量。"""
    from build_a_share_core_valuation_pool import build_pool

    valuation = [{
        "security_code": "600519", "security_name": "贵州茅台", "quality_tier": "L1",
        "valuation_tier": "中性", "fair_price_low": "1600", "fair_price_high": "2000",
        "band_derivation": "dossier", "anchor_basis": "x", "band_sensitivity": "y",
    }]
    tiers = [{"security_code": "600519", "quality_tier": "L1", "quality_tier_label": "L1"}]
    rows = build_pool(valuation, tiers, "2026-08-03", Path("data/processed/custom_valuation.csv"))
    if not rows:
        return ["build_pool 未产出行，无法校验溯源"]
    got = rows[0].get("source_file", "")
    if "custom_valuation.csv" not in got:
        return [f"source_file 未反映实际入参，实得 '{got}'"]
    return []


def case_holdings_provenance_uses_actual_path():
    import inspect
    src = inspect.getsource(tracker.log_decisions)
    if "DEFAULT_VALUATION_POOL}" in src:
        return ["log_decisions 仍把硬编码默认池路径写进 input_files"]
    return [] if "pool_file}" in src else ["log_decisions 未记录实际池文件路径"]


CASES = [
    ("无行情不得判『持有』（核心）", case_no_quote_is_not_hold),
    ("无行情不得断言割肉未触及", case_no_quote_never_claims_stop_checked),
    ("跌破割肉价仍被识别", case_stop_breach_still_detected),
    ("正常交易日判『持有』", case_normal_day_is_hold),
    ("全市场取数失败非 0 退出", case_all_rows_failed_is_not_success),
    ("扫描 0 行非 0 退出", case_empty_scan_is_not_success),
    ("个别停牌不中断整批", case_isolated_failures_still_pass),
    ("池溯源写实际入参路径", case_pool_provenance_uses_actual_path),
    ("持仓溯源写实际池路径", case_holdings_provenance_uses_actual_path),
]


def main() -> int:
    failed = 0
    for name, run in CASES:
        try:
            problems = run()
        except Exception as exc:  # noqa: BLE001 - a crashing case is a failing case
            problems = [f"用例抛异常：{exc!r}"]
        print(f"  {'PASS' if not problems else 'FAIL'}  {name}")
        for p in problems:
            print(f"        {p}")
        failed += bool(problems)
    print(f"\n{len(CASES) - failed}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
