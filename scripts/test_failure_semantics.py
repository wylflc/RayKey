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

All three are the same defect class — §13 第 3 条「静默失效」, a failure that
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
}
POOL_ROW = {
    "security_code": "600519",
    "quality_tier": "L1",
    "fair_price_low": "1600",
    "fair_price_high": "2000",
}


def run_tracker(price, *, pool=True, monkey_quotes=None):
    """Drive tracker.track() with the network stubbed out."""
    holding = dict(HOLDING)
    quotes = monkey_quotes if monkey_quotes is not None else (
        {} if price is None else {"600519": {"price": price}}
    )

    real_fetch, real_load, real_open = tracker.fetch_spot_quotes, tracker.load_pool, Path.open
    real_raw = tracker.fetch_raw_close
    real_bands = tracker.MODEL_BANDS
    tracker.MODEL_BANDS = {}   # 桩掉生产带：无带行 → pv 退回带中值（有带行时走 pv_ratio.trading_pv，v4.62/OI-091）

    class FakeFile:
        def __enter__(self):
            header = ",".join(holding)
            return iter([header, ",".join(str(holding[k]) for k in holding)])

        def __exit__(self, *a):
            return False

    tracker.fetch_spot_quotes = lambda *a, **k: quotes
    # OI-067（v4.20）后历史日期走日线接口 `fetch_raw_close`，同样必须打桩——
    # 否则测试会拿真实收盘价盖掉 canned price（2026-08-19 实测 4 个用例因此假失败）。
    # 返回 `(收盘, 当日MA20, 当日MA60)` 三元组，**三个位置都要给**——少给一个会让
    # 全部依赖它的用例以解包异常整体失败，而不是报出真实断言。
    # MA20 打桩为高于收盘 5%：§9.3.2 减持闸门是「收盘 < MA20」，打 None 会走「均线缺失、
    # 不减、等数据齐」那一支，越线用例就永远读不到点名备注。MA60 仍打 None = 均线不可得，
    # 止损退回按锚判读，与旧冻结口径逐位一致。
    tracker.fetch_raw_close = lambda code, as_of, timeout: (
        price, (price * 1.05 if price else None), None)
    tracker.load_pool = lambda *a, **k: ({"600519": POOL_ROW} if pool else {})
    Path.open = lambda self, *a, **k: FakeFile()  # type: ignore[assignment]
    try:
        return tracker.track(Path("x.csv"), Path("y.csv"), date(2026, 8, 3), "", 8.0)[0]
    finally:
        tracker.fetch_spot_quotes, tracker.load_pool, Path.open = real_fetch, real_load, real_open
        tracker.fetch_raw_close = real_raw
        tracker.MODEL_BANDS = real_bands


def case_no_quote_is_not_hold():
    """核心用例：取不到行情时动作必须是 `数据缺失`，绝不能是 `持有`。

    旧版落 `持有` 并在备注写「沿用上一交易日结论」，而脚本从不读上一日文件——
    一只涨幅已达标、本该按 §9.3.2 减持的停牌股会显示为持有，
    在卖出规则上制造静默失效（v2.56 前该缺陷作用于割肉价，同型）。
    """
    row = run_tracker(None)
    if row["action"] == "持有":
        return ["无行情却判 `持有` —— 正是本测试要拦的那个缺陷"]
    if row["action"] != "数据缺失":
        return [f"无行情时应判 `数据缺失`，实得 `{row['action']}`"]
    if "沿用上一交易日" in str(row.get("note", "")):
        return ["备注仍声称『沿用上一交易日结论』，但脚本并未读取上一日文件"]
    return []


def case_no_quote_leaves_pv_empty():
    """无行情时 `pv` 必须为空——空值代表「没算」，0 或沿用旧值都会被下游当成真数。"""
    row = run_tracker(None)
    return [] if row.get("pv") == "" else [f"无行情时 `pv` 应为空，实得 `{row.get('pv')}`"]


def case_pv_computed_against_band_mid():
    """无生产带行时 P/V 退回带中值（有带行走 `pv_ratio.trading_pv`，v4.62/OI-091），不是对带下沿或上沿。"""
    row = run_tracker(1800.0)  # 带 1600-2000，中值 1800 → P/V = 1.00
    if row["pv"] != "1.00":
        return [f"带中值 1800、现价 1800 应得 P/V=1.00，实得 `{row['pv']}`"]
    return [] if row["action"] == "持有" else [f"正常日应判 `持有`，实得 `{row['action']}`"]


def case_gain_over_trim_line_is_flagged_in_note():
    """涨幅越过 §9.3.1 涨幅减持线必须在备注点名——它是本脚本唯一会点名的减持条件，静默即失效。

    **阈值从 `tracker.GAIN_SELL` 读，不写字面量**——写死就会在下一次改线时静默失效，
    而这个测试的全部意义正是拦住静默失效（v2.98 改线时踩到过：原用例钉死 1.10）。
    """
    cost = float(HOLDING["cost_basis"])
    price = cost * (1.0 + tracker.GAIN_SELL) * 1.1    # 稳稳越线
    row = run_tracker(price)
    expect = f"{price / 1800.0:.2f}"
    if row["pv"] != expect:
        return [f"应得 P/V={expect}，实得 `{row['pv']}`"]
    if f"{tracker.GAIN_SELL:.0%}" not in str(row.get("note", "")):
        return ["涨幅已越减持线却未在备注点名（§9.3.2 第四步）"]
    return []


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
        "fair_price_low": "1600", "fair_price_high": "2000",
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
    ("无行情时 P/V 必须为空", case_no_quote_leaves_pv_empty),
    ("P/V 对带中值计算", case_pv_computed_against_band_mid),
    ("涨幅越减持线必须点名", case_gain_over_trim_line_is_flagged_in_note),
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
