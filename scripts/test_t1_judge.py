#!/usr/bin/env python3
"""研究开关 `--t1-judge`（涨幅减持／换仓卖出源／合格集只按 T+1 收盘判）与 `--stop-basis both` 的回归测试。

每个用例都构造「T 日不成立、T+1 收盘成立」（或反之）的价格路径，核对开关改变的只是那一笔的成交日与价格。
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


class T1JudgeTest(unittest.TestCase):
    def run_case(self, states, *, x: float = 0.05, swap: bool = False,
                 t1_judge: frozenset[str] = frozenset(), stop_basis: str = "exec"):
        bt.DELISTED_LAST.clear()
        ledger: list = []
        bt.run(
            "trend", x, states, market(states), {}, flat_mas(states),
            min(states), max(states), 100_000.0,
            width=-0.0454, trend_tranche=True, trend_ma=(20, 60),   # 买入线 1.0454（与 BASE 同号）
            exec_delay=1, exec_price="close",
            stop_ma=60, stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.10, gain_sell_mode="ungated",
            swap=swap, swap_margin=0.15, swap_partial=True, swap_require_weak=True, swap_weak_ma=20,
            swap_gain_once=True, lot_size=100, stop_basis=stop_basis, t1_judge=t1_judge,
            ledger=ledger,
        )
        return ledger

    @staticmethod
    def fills(ledger, action: str) -> list[tuple[str, str, float]]:
        return [(r["date"], r["security_code"], float(r["price"])) for r in ledger if r["action"] == action]

    # ---- 止损：01-03 成交价 7.5 已在锚 8 之下（跳空建仓），01-04 收盘 8.4 站回线上，01-05 收盘 7.0 再破。
    STOP_STATES = {
        "2024-01-02": [row("A", 10.0, 12.5)],
        "2024-01-03": [row("A", 7.5, 12.5)],
        "2024-01-04": [row("A", 8.4, 12.5)],
        "2024-01-05": [row("A", 7.0, 12.5)],
        "2024-01-08": [row("A", 7.2, 12.5)],
    }

    def test_stop_exec_waits_for_exec_day_breach(self) -> None:
        sells = self.fills(self.run_case(self.STOP_STATES), "卖出")
        self.assertEqual(sells[:1], [("2024-01-05", "A", 7.0)])

    def test_stop_signal_sells_next_day_after_signal_breach(self) -> None:
        sells = self.fills(self.run_case(self.STOP_STATES, stop_basis="signal"), "卖出")
        self.assertEqual(sells[:1], [("2024-01-04", "A", 8.4)])

    def test_stop_both_fires_on_either_breach(self) -> None:
        sells = self.fills(self.run_case(self.STOP_STATES, stop_basis="both"), "卖出")
        self.assertEqual(sells[:1], [("2024-01-04", "A", 8.4)])

    # ---- 涨幅减持：均价 10.5，线 22.05；01-04 收盘 21.5 未到、01-05 收盘 22.5 达标。
    GAIN_STATES = {
        "2024-01-02": [row("A", 10.0, 12.5)],
        "2024-01-03": [row("A", 10.5, 9.0)],
        "2024-01-04": [row("A", 21.5, 9.0)],
        "2024-01-05": [row("A", 22.5, 9.0)],
        "2024-01-08": [row("A", 22.6, 9.0)],
    }

    def test_gain_base_trims_day_after_signal(self) -> None:
        sells = self.fills(self.run_case(self.GAIN_STATES), "卖出")
        self.assertEqual(sells[:1], [("2024-01-08", "A", 22.6)])

    def test_gain_t1_trims_on_exec_day_close(self) -> None:
        sells = self.fills(self.run_case(self.GAIN_STATES, t1_judge=frozenset({"gain"})), "卖出")
        self.assertEqual(sells[:1], [("2024-01-05", "A", 22.5)])

    # ---- 换仓卖出源：A 01-03 收盘 10.5 ≥ MA20 9 不弱势，01-04 收盘 8.5 弱势；B 01-03 起合格且资金不足。
    # BASE 要等 01-04 信号日弱势成立、01-05 成交；`t1_judge={"swap"}` 在 01-04 收盘即判弱势并当日换仓。
    SWAP_STATES = {
        "2024-01-02": [row("A", 10.0, 12.5)],
        "2024-01-03": [row("A", 10.5, 12.5), row("B", 10.0, 20.0)],
        "2024-01-04": [row("A", 8.5, 12.5), row("B", 10.2, 20.0)],
        "2024-01-05": [row("A", 8.6, 12.5), row("B", 10.3, 20.0)],
    }

    def test_swap_base_needs_signal_day_weakness(self) -> None:
        ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True)
        self.assertEqual(self.fills(ledger, "卖出"), [("2024-01-05", "A", 8.6)])
        self.assertIn(("2024-01-05", "B", 10.3), self.fills(ledger, "买入"))

    def test_swap_t1_uses_exec_day_weakness_and_margin(self) -> None:
        ledger = self.run_case(self.SWAP_STATES, x=1.0, swap=True, t1_judge=frozenset({"swap"}))
        sells = self.fills(ledger, "卖出")
        self.assertEqual(sells, [("2024-01-04", "A", 8.5)])
        self.assertIn("换仓", [r for r in ledger if r["action"] == "卖出"][0]["reason"])
        self.assertIn(("2024-01-04", "B", 10.2), self.fills(ledger, "买入"))

    # ---- 合格集：01-02 P/V 1.10 不过线，01-03 收盘 12.5 ÷ T 日 V 12.5 = 1.00 过线。
    BUY_STATES = {
        "2024-01-02": [row("A", 13.75, 12.5)],
        "2024-01-03": [row("A", 12.5, 12.5)],
        "2024-01-04": [row("A", 12.6, 12.5)],
        "2024-01-05": [row("A", 12.7, 12.5)],
    }

    def test_buy_base_fills_day_after_signal(self) -> None:
        buys = self.fills(self.run_case(self.BUY_STATES), "买入")
        self.assertEqual(buys[:1], [("2024-01-04", "A", 12.6)])

    def test_buy_t1_forms_eligible_set_on_exec_day_close(self) -> None:
        buys = self.fills(self.run_case(self.BUY_STATES, t1_judge=frozenset({"buy"})), "买入")
        self.assertEqual(buys[:1], [("2024-01-03", "A", 12.5)])

    def test_off_switches_are_bitwise_neutral(self) -> None:
        for states, kw in ((self.GAIN_STATES, {}), (self.SWAP_STATES, {"x": 1.0, "swap": True}),
                           (self.BUY_STATES, {}), (self.STOP_STATES, {})):
            self.assertEqual(self.run_case(states, **kw), self.run_case(states, t1_judge=frozenset(), **kw))


if __name__ == "__main__":
    unittest.main()
