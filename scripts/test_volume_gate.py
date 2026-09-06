#!/usr/bin/env python3
"""成交量闸门研究开关（--vol-entry-min/max、--vol-addon-min/max、--vol-swap-min/max、--vol-stop-min）的回归测试。

夹具沿用 test_t1_judge／test_swap_weak_regime 的价格路径，量比直接以 `vols[代码][日]` 注入；
另测 `volume_ratio_series` 的除权折算与窗口定义。
"""

from __future__ import annotations

import unittest

import backtest_valuation_strategy as bt


def row(code: str, close: float, value: float) -> tuple[str, float, float, float]:
    return code, close, value, close / value


def market(days):
    prices: dict[str, dict[str, float]] = {}
    for day, rows in days.items():
        for code, close, _value, _ratio in rows:
            prices.setdefault(code, {})[day] = close
    return prices


def flat_mas(states, codes=("A", "B")):
    return {c: {d: {20: 9.0, 60: 8.0} for d in states} for c in codes}


class _ListWriter:
    def __init__(self) -> None:
        self.rows: list[list] = []

    def writerow(self, r) -> None:
        self.rows.append(list(r))


class VolumeRatioSeriesTest(unittest.TestCase):
    DAYS = [f"2024-{m:02d}-{d:02d}" for m in (1, 2) for d in range(1, 29)][:30]

    def test_exclusive_window_and_split_adjustment(self) -> None:
        # 前 25 日成交量 100，第 26 日起 10 送 10（股本翻倍）后成交量 200：折算后量比应为 1.0，不折算会读成 2.0。
        series = {d: (100.0 if i < 25 else 200.0) for i, d in enumerate(self.DAYS)}
        events = {self.DAYS[25]: (0.0, 1.0, 0.0, 0.0)}
        ratios = bt.volume_ratio_series(series, events, 20)
        self.assertNotIn(self.DAYS[19], ratios)                       # 此前不足 20 日
        self.assertAlmostEqual(ratios[self.DAYS[20]], 1.0)
        self.assertAlmostEqual(ratios[self.DAYS[25]], 1.0)             # 除权日
        self.assertAlmostEqual(ratios[self.DAYS[29]], 1.0)
        raw = bt.volume_ratio_series(series, {}, 20)
        self.assertAlmostEqual(raw[self.DAYS[25]], 2.0)
        # 当日÷此前均量不含当日：第 21 日放量 300 → 3.0，第 22 日回到 100 → 100 ÷ ((19×100+300)/20) = 0.909
        series2 = {d: 100.0 for d in self.DAYS}
        series2[self.DAYS[20]] = 300.0
        r2 = bt.volume_ratio_series(series2, {}, 20)
        self.assertAlmostEqual(r2[self.DAYS[20]], 3.0)
        self.assertAlmostEqual(r2[self.DAYS[21]], 100.0 / ((19 * 100.0 + 300.0) / 20))

    def test_trend_form_is_short_over_long_inclusive(self) -> None:
        series = {d: 100.0 for d in self.DAYS}
        for d in self.DAYS[20:25]:
            series[d] = 200.0
        r = bt.volume_ratio_series(series, {}, 20, short=5)
        self.assertNotIn(self.DAYS[18], r)
        self.assertAlmostEqual(r[self.DAYS[19]], 1.0)
        self.assertAlmostEqual(r[self.DAYS[24]], 200.0 / ((15 * 100.0 + 5 * 200.0) / 20))
        self.assertEqual(bt.volume_ratio_series(series, {}, 5, short=5), {})


class VolumeGateTest(unittest.TestCase):
    def run_case(self, states, *, x: float = 0.05, swap: bool = False, mas=None, block_log=None, **extra):
        bt.DELISTED_LAST.clear()
        ledger: list = []
        result = bt.run(
            "trend", x, states, market(states), {}, mas or flat_mas(states),
            min(states), max(states), 100_000.0,
            width=-0.0454, trend_tranche=True, trend_ma=(20, 60),
            exec_delay=1, exec_price="close", sell_trend_ma=(20,),
            stop_ma=60, stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.10, gain_sell_mode="ungated",
            swap=swap, swap_margin=0.15, swap_partial=True, swap_require_weak=True, swap_weak_ma=20,
            swap_gain_once=True, lot_size=100, weak_block_log=block_log, ledger=ledger, **extra,
        )
        return result, ledger

    @staticmethod
    def fills(ledger, action: str) -> list[tuple[str, str, float]]:
        return [(r["date"], r["security_code"], float(r["price"])) for r in ledger if r["action"] == action]

    # ---- 新建仓：01-03 起 A 合格（P/V 1.00、收盘 > MA20 9 > MA60 8）。
    BUY_STATES = {
        "2024-01-02": [row("A", 13.75, 12.5)],
        "2024-01-03": [row("A", 12.5, 12.5)],
        "2024-01-04": [row("A", 12.6, 12.5)],
        "2024-01-05": [row("A", 12.7, 12.5)],
    }

    def test_entry_min_blocks_quiet_day_and_missing_ratio(self) -> None:
        vols = {"A": {"2024-01-03": 0.5, "2024-01-04": 1.5}}
        res, ledger = self.run_case(self.BUY_STATES, vols=vols, vol_entry_min=1.0)
        self.assertEqual(self.fills(ledger, "买入")[:1], [("2024-01-05", "A", 12.7)])   # 01-04 信号日放量才建仓
        self.assertEqual(res["stats"]["成交量·新建仓挡下"], 1)
        _res, ledger = self.run_case(self.BUY_STATES, vols={"A": {}}, vol_entry_min=1.0)
        self.assertEqual(self.fills(ledger, "买入"), [])                                # 量比缺失视同不合格
        _res, ledger = self.run_case(self.BUY_STATES, vols=vols, vol_entry_max=1.0)
        self.assertEqual(self.fills(ledger, "买入")[:1], [("2024-01-04", "A", 12.6)])   # 上限只挡 01-04 的 1.5

    def test_addon_range_only_applies_to_held_codes(self) -> None:
        # 01-03 建仓（量比 1.5 过 min 1.0），01-04 信号日量比 1.2 > 加仓上限 0.8 → 挡下；01-05 量比 0.5 → 加仓。
        states = {**self.BUY_STATES, "2024-01-08": [row("A", 12.8, 12.5)]}
        vols = {"A": {"2024-01-03": 1.5, "2024-01-04": 1.2, "2024-01-05": 0.5}}
        res, ledger = self.run_case(states, vols=vols, vol_entry_min=1.0, vol_addon_max=0.8)
        self.assertEqual(self.fills(ledger, "买入"), [("2024-01-04", "A", 12.6), ("2024-01-08", "A", 12.8)])
        self.assertEqual(res["stats"]["成交量·加仓挡下"], 1)
        self.assertNotIn("成交量·新建仓挡下", res["stats"])

    # ---- 换仓卖出源：A 01-04 收盘 8.5 < MA20 9 弱势；B 01-03 起合格且资金不足（x=1.0）。
    SWAP_STATES = {
        "2024-01-02": [row("A", 10.0, 12.5)],
        "2024-01-03": [row("A", 10.5, 12.5), row("B", 10.0, 20.0)],
        "2024-01-04": [row("A", 8.5, 12.5), row("B", 10.2, 20.0)],
        "2024-01-05": [row("A", 8.6, 12.5), row("B", 10.3, 20.0)],
    }

    def test_swap_source_requires_volume_confirmation(self) -> None:
        log = _ListWriter()
        quiet = {"A": {"2024-01-04": 0.5, "2024-01-05": 0.5}, "B": {}}
        res, ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True, vols=quiet, vol_swap_min=1.0, block_log=log)
        self.assertEqual(self.fills(ledger, "卖出"), [])
        self.assertEqual(res["stats"]["换仓卖出源·形态复核挡下"], 1)
        self.assertTrue(str(log.rows[0][11]).startswith("量比0.50<1"))
        loud = {"A": {"2024-01-04": 1.5, "2024-01-05": 1.5}, "B": {}}
        _res, ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True, vols=loud, vol_swap_min=1.0)
        self.assertEqual(self.fills(ledger, "卖出"), [("2024-01-05", "A", 8.6)])
        _res, ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True, vols=loud, vol_swap_max=1.0)
        self.assertEqual(self.fills(ledger, "卖出"), [])                                # 反向：放量跌破不换
        _res, ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True, vols={"A": {}, "B": {}}, vol_swap_min=1.0)
        self.assertEqual(self.fills(ledger, "卖出"), [])                                # 缺失不作卖出源

    # ---- 止损：01-03 成交价 7.5 在锚 8 之下，01-04 收盘 8.4 站回，01-05 收盘 7.0 再破（成交日判）。
    STOP_STATES = {
        "2024-01-02": [row("A", 10.0, 12.5)],
        "2024-01-03": [row("A", 7.5, 12.5)],
        "2024-01-04": [row("A", 8.4, 12.5)],
        "2024-01-05": [row("A", 7.0, 12.5)],
        "2024-01-08": [row("A", 7.2, 12.5)],
    }

    def test_stop_waits_for_volume_confirmation_but_fires_on_missing(self) -> None:
        _res, ledger = self.run_case(self.STOP_STATES)
        self.assertEqual(self.fills(ledger, "卖出")[:1], [("2024-01-05", "A", 7.0)])
        quiet_then_loud = {"A": {"2024-01-05": 0.5, "2024-01-08": 1.2}}
        res, ledger = self.run_case(self.STOP_STATES, vols=quiet_then_loud, vol_stop_min=1.0)
        self.assertEqual(self.fills(ledger, "卖出")[:1], [("2024-01-08", "A", 7.2)])
        self.assertEqual(res["stats"]["止损·缩量跌破不触发"], 1)
        _res, ledger = self.run_case(self.STOP_STATES, vols={"A": {}}, vol_stop_min=1.0)
        self.assertEqual(self.fills(ledger, "卖出")[:1], [("2024-01-05", "A", 7.0)])   # 缺失照常触发

    def test_off_switches_are_bitwise_neutral(self) -> None:
        vols = {"A": {d: 0.3 for d in self.STOP_STATES}, "B": {d: 0.3 for d in self.SWAP_STATES}}
        for states, kw in ((self.BUY_STATES, {}), (self.SWAP_STATES, {"x": 1.0, "swap": True}), (self.STOP_STATES, {})):
            plain, _ = self.run_case(states, **kw)
            same, _ = self.run_case(states, vols=vols, **kw)
            self.assertEqual(plain, same)


if __name__ == "__main__":
    unittest.main()
