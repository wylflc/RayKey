#!/usr/bin/env python3
"""换仓卖出源弱势的形态复核研究开关（--swap-weak-days／--swap-weak-slope／--swap-weak-max-cross／--swap-source-cooldown）
与被挡事件记录（--weak-block-log）的回归测试。夹具沿用 test_sell_confirmation 的 H→X 换仓场景。"""

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


class _ListWriter:
    def __init__(self) -> None:
        self.rows: list[list] = []

    def writerow(self, r) -> None:
        self.rows.append(list(r))


# D0 信号 D1 建仓（x=100% 用尽资金）；D2 信号：H 收盘 10 < MA20 11 弱势、X P/V 0.5 合格且资金不足 → 换仓；D3 成交。
SWAP_STATES = {
    "2024-01-02": [row("H", 10.0, 20.0)],
    "2024-01-03": [row("H", 10.0, 20.0), row("X", 20.0, 10.0)],
    "2024-01-04": [row("H", 10.0, 8.0), row("X", 10.0, 20.0)],
    "2024-01-05": [row("H", 10.0, 8.0), row("X", 10.0, 20.0)],
}
X_MAS = {"2024-01-03": {20: 19.0, 60: 18.0}, "2024-01-04": {20: 9.0, 60: 8.0}, "2024-01-05": {20: 9.0, 60: 8.0}}


def h_mas(ma20_by_day: dict[str, float]) -> dict[str, dict[int, float]]:
    return {d: {20: m, 60: 8.0} for d, m in ma20_by_day.items()}


class SwapWeakRegimeTest(unittest.TestCase):
    def run_case(self, states, mas, *, x: float = 1.0, block_log=None, **extra):
        bt.DELISTED_LAST.clear()
        return bt.run(
            "trend", x, states, market(states), {}, mas,
            min(states), max(states), 100_000.0,
            width=-0.0454, trend_tranche=True, trend_ma=(20, 60),
            exec_delay=1, exec_price="close", sell_trend_ma=(20,),
            stop_ma=60, stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.10, gain_sell_mode="ungated", swap_gain_once=True,
            swap=True, swap_margin=0.15, swap_partial=True,
            swap_require_weak=True, swap_weak_ma=20, weak_block_log=block_log,
            **extra,
        )

    # 现行：D0/D1 MA20 9（收盘在线上）、D2 起 11（收盘在线下）→ 单日弱势即换仓。
    PLAIN_MAS = {"H": h_mas({"2024-01-02": 9.0, "2024-01-03": 9.0, "2024-01-04": 11.0, "2024-01-05": 11.0}), "X": X_MAS}

    def test_defaults_are_bitwise_plain(self) -> None:
        plain = self.run_case(SWAP_STATES, self.PLAIN_MAS)
        self.assertEqual((plain["sells"], plain["buys"]), (1, 2))
        same = self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_days=1, swap_weak_slope=0,
                             swap_weak_max_cross=0, swap_source_cooldown=0)
        self.assertEqual((same["sells"], same["buys"]), (1, 2))

    def test_persistence_requires_n_consecutive_signal_days(self) -> None:
        # D2 是首个线下日：连续 1 日 < 2 → 挡下；D1 也在线下（MA20 11）则连续 2 日 → 放行。
        log = _ListWriter()
        blocked = self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_days=2, block_log=log)
        self.assertEqual((blocked["sells"], blocked["buys"]), (0, 1))
        self.assertEqual(blocked["stats"]["换仓卖出源·形态复核挡下"], 1)
        self.assertEqual(len(log.rows), 1)
        self.assertEqual(log.rows[0][:3], ["2024-01-04", "2024-01-05", "H"])
        self.assertEqual(log.rows[0][9], "X")                       # 触发候选
        self.assertTrue(str(log.rows[0][11]).startswith("连续1日<2"))
        two_days = {"H": h_mas({"2024-01-02": 9.0, "2024-01-03": 11.0, "2024-01-04": 11.0, "2024-01-05": 11.0}), "X": X_MAS}
        allowed = self.run_case(SWAP_STATES, two_days, swap_weak_days=2)
        self.assertEqual((allowed["sells"], allowed["buys"]), (1, 2))

    def test_slope_requires_falling_ma(self) -> None:
        # D2 MA20 11 > D1 的 9：均线上行 → 挡下；D1 为 12 则 11 < 12 下行 → 放行。
        blocked = self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_slope=1)
        self.assertEqual((blocked["sells"], blocked["buys"]), (0, 1))
        falling = {"H": h_mas({"2024-01-02": 9.0, "2024-01-03": 12.0, "2024-01-04": 11.0, "2024-01-05": 11.0}), "X": X_MAS}
        allowed = self.run_case(SWAP_STATES, falling, swap_weak_slope=1)
        self.assertEqual((allowed["sells"], allowed["buys"]), (1, 2))
        # 均线历史不足（k=5 而只有 3 个交易日）：判不了下行 → 不算弱势。
        short = self.run_case(SWAP_STATES, falling, swap_weak_slope=5)
        self.assertEqual(short["sells"], 0)

    def test_cross_count_marks_oscillation_regime(self) -> None:
        # 现行夹具 D0/D1 线上、D2 线下：穿越 1 次 < 2 → 放行；D0 线下／D1 线上／D2 线下：穿越 2 次 → 挡下。
        allowed = self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_max_cross=2, swap_weak_cross_window=20)
        self.assertEqual((allowed["sells"], allowed["buys"]), (1, 2))
        chop = {"H": h_mas({"2024-01-02": 11.0, "2024-01-03": 9.0, "2024-01-04": 11.0, "2024-01-05": 11.0}), "X": X_MAS}
        blocked = self.run_case(SWAP_STATES, chop, swap_weak_max_cross=2, swap_weak_cross_window=20)
        self.assertEqual((blocked["sells"], blocked["buys"]), (0, 1))
        # 回看窗只有 2 日时 D0 的穿越落到窗外：只剩 1 次 → 放行。
        windowed = self.run_case(SWAP_STATES, chop, swap_weak_max_cross=2, swap_weak_cross_window=2)
        self.assertEqual(windowed["sells"], 1)

    def test_cooldown_blocks_second_swap_out_of_same_holding(self) -> None:
        # x=50%：D1、D2 各买 H 一档用尽资金；D3 X 触发换出 H 一档；D4 未持仓 Y 触发再换 H 一档。
        states = {
            "2024-01-02": [row("H", 10.0, 20.0)],
            "2024-01-03": [row("H", 10.0, 20.0)],
            "2024-01-04": [row("H", 10.0, 8.0), row("X", 10.0, 20.0)],
            "2024-01-05": [row("H", 10.0, 8.0), row("X", 10.0, 20.0), row("Y", 10.0, 20.0)],
            "2024-01-08": [row("H", 10.0, 8.0), row("X", 10.0, 20.0), row("Y", 10.0, 20.0)],
            "2024-01-09": [row("H", 10.0, 8.0), row("X", 10.0, 20.0), row("Y", 10.0, 20.0)],
        }
        mas = {
            "H": h_mas({d: (9.0 if d < "2024-01-04" else 11.0) for d in states}),
            "X": {d: {20: 9.0, 60: 8.0} for d in states if d >= "2024-01-04"},
            "Y": {d: {20: 9.0, 60: 8.0} for d in states if d >= "2024-01-05"},
        }
        plain = self.run_case(states, mas, x=0.5)
        self.assertEqual(plain["sells"], 2)                      # D3、D4 各换出一档，H 清空
        cooled = self.run_case(states, mas, x=0.5, swap_source_cooldown=5)
        self.assertEqual(cooled["sells"], 1)                     # D4、D5 都在冷却期内
        self.assertEqual(cooled["stats"]["换仓卖出源·形态复核挡下"], 2)
        # 冷却 1 日：D4 被挡、D5 过期后照常换出——总笔数与现行相同，只是推迟一日。
        short = self.run_case(states, mas, x=0.5, swap_source_cooldown=1)
        self.assertEqual(short["sells"], 2)
        self.assertEqual(short["stats"]["换仓卖出源·形态复核挡下"], 1)

    def test_slope_min_requires_material_decline(self) -> None:
        # D1 MA20 11.05 → D2 11.0：下行 0.45%；阈值 0.5% 挡下、0.4% 放行；不给阈值时严格低于即放行。
        mas = {"H": h_mas({"2024-01-02": 9.0, "2024-01-03": 11.05, "2024-01-04": 11.0, "2024-01-05": 11.0}), "X": X_MAS}
        self.assertEqual(self.run_case(SWAP_STATES, mas, swap_weak_slope=1)["sells"], 1)
        self.assertEqual(self.run_case(SWAP_STATES, mas, swap_weak_slope=1, swap_weak_slope_min=0.005)["sells"], 0)
        self.assertEqual(self.run_case(SWAP_STATES, mas, swap_weak_slope=1, swap_weak_slope_min=0.004)["sells"], 1)

    def test_deep_break_waives_form_checks_but_not_cooldown(self) -> None:
        # 现行夹具 D2 收盘 10 对 MA20 11 = 低 9.1%：deep 5% 下连续日／斜率复核免除 → 照常换仓；deep 10% 不免除 → 挡下。
        self.assertEqual(self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_days=2)["sells"], 0)
        self.assertEqual(self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_days=2, swap_weak_deep=0.05)["sells"], 1)
        self.assertEqual(self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_days=2, swap_weak_deep=0.10)["sells"], 0)
        self.assertEqual(self.run_case(SWAP_STATES, self.PLAIN_MAS, swap_weak_slope=1, swap_weak_deep=0.05)["sells"], 1)


if __name__ == "__main__":
    unittest.main()
