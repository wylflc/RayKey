#!/usr/bin/env python3
"""T 日发信号、T+1 收盘复核同一价格触发操作的回归测试。"""

from __future__ import annotations

import unittest

import backtest_valuation_strategy as bt


def row(code: str, close: float, value: float) -> tuple[str, float, float, float]:
    return code, close, value, close / value


def market(days: dict[str, list[tuple[str, float, float, float]]]):
    prices: dict[str, dict[str, float]] = {}
    for day, rows in days.items():
        for code, close, _value, _ratio in rows:
            prices.setdefault(code, {})[day] = close
    return prices


class FakeCorrelations:
    def get(self, a: str, b: str, day: str):
        return 1.0 if a == b else 0.9


class T1ExecutionConfirmationTest(unittest.TestCase):
    def run_case(self, states, mas, *, confirm: bool, x: float = 0.05,
                 swap: bool = False, corr=None):
        bt.DELISTED_LAST.clear()
        return bt.run(
            "trend", x, states, market(states), {}, mas,
            min(states), max(states), 100_000.0,
            width=0.0657, trend_tranche=True, trend_ma=(20, 60),
            exec_delay=1, exec_price="close", sell_trend_ma=(20,),
            sell_line_override=2.4671, stop_ma=60,
            stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.25, gain_sell_mode="gated",
            swap=swap, swap_margin=0.1437, swap_partial=True,
            swap_require_weak=True, swap_weak_ma=20,
            corr=corr, max_corr=0.7 if corr else 0.0,
            exec_confirm_close=confirm,
        )

    def test_new_entry_is_cancelled_when_t1_close_loses_ma20(self) -> None:
        states = {
            "2024-01-02": [row("A", 10.0, 12.0)],
            "2024-01-03": [row("A", 8.5, 10.5)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=False)["buys"], 1)
        confirmed = self.run_case(states, mas, confirm=True)
        self.assertEqual(confirmed["buys"], 0)
        self.assertEqual(confirmed["stats"]["T+1确认·建仓取消·收盘未站上均线"], 1)

    def test_confirmation_freezes_signal_day_value(self) -> None:
        # T+1 状态里的 V 即使因新报告改变，价格确认也只冻结 T 日 V=12、用 10/12 复核；
        # 否则读 T+1 V=5 会把 P/V 算成 2 并错误取消。
        states = {
            "2024-01-02": [row("A", 10.0, 12.0)],
            "2024-01-03": [row("A", 10.0, 5.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=True)["buys"], 1)

    def test_new_entry_is_cancelled_when_t1_price_loses_value_line(self) -> None:
        states = {
            "2024-01-02": [row("A", 10.0, 12.0)],
            "2024-01-03": [row("A", 12.0, 12.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=False)["buys"], 1)
        confirmed = self.run_case(states, mas, confirm=True)
        self.assertEqual(confirmed["buys"], 0)
        self.assertEqual(confirmed["stats"]["T+1确认·买入取消·P/V"], 1)

    def test_existing_holding_addon_keeps_ma_only_price_rule(self) -> None:
        # 生产口径下已有持仓加仓只要求 MA20>MA60；T+1 收盘低于 MA20 不应取消。
        states = {
            "2024-01-02": [row("A", 10.0, 20.0)],
            "2024-01-03": [row("A", 10.0, 20.0)],
            "2024-01-04": [row("A", 8.5, 20.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
            "2024-01-04": {20: 9.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=True)["buys"], 2)

    def test_failed_candidate_does_not_promote_correlated_runner_up(self) -> None:
        # T 日 A 排第一并在相关性过滤中挡住 B；A 到 T+1 失效后应空过，不能改买 B。
        states = {
            "2024-01-02": [row("A", 10.0, 20.0), row("B", 10.0, 16.0)],
            "2024-01-03": [row("A", 20.0, 20.0), row("B", 10.0, 16.0)],
        }
        mas = {
            "A": {
                "2024-01-02": {20: 9.0, 60: 8.0},
                "2024-01-03": {20: 9.0, 60: 8.0},
            },
            "B": {
                "2024-01-02": {20: 9.0, 60: 8.0},
                "2024-01-03": {20: 9.0, 60: 8.0},
            },
        }
        confirmed = self.run_case(states, mas, confirm=True, corr=FakeCorrelations())
        self.assertEqual(confirmed["buys"], 0)
        self.assertEqual(confirmed["stats"]["T+1确认·买入取消·P/V"], 1)

    def test_trim_is_cancelled_when_t1_close_recovers_above_ma20(self) -> None:
        # D0 信号在 D1 建仓；D2 发出“贵且弱”的减持信号；D3 收盘重新站回 MA20。
        states = {
            "2024-01-02": [row("A", 10.0, 20.0)],
            "2024-01-03": [row("A", 10.0, 20.0)],
            "2024-01-04": [row("A", 10.0, 4.0)],
            "2024-01-05": [row("A", 12.0, 100.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
            "2024-01-04": {20: 11.0, 60: 8.0},
            "2024-01-05": {20: 11.5, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=False)["sells"], 1)
        confirmed = self.run_case(states, mas, confirm=True)
        self.assertEqual(confirmed["sells"], 0)
        self.assertEqual(confirmed["stats"]["T+1确认·减持取消·收盘站回均线"], 1)

    def test_gain_trim_is_cancelled_when_t1_gain_falls_below_line(self) -> None:
        states = {
            "2024-01-02": [row("A", 10.0, 20.0)],
            # D1 仍作为 D0 建仓的成交日，但自身 P/V 已不满足买线，避免 D2 再加仓抬高成本。
            "2024-01-03": [row("A", 10.0, 5.0)],
            "2024-01-04": [row("A", 23.0, 100.0)],
            "2024-01-05": [row("A", 20.0, 100.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
            "2024-01-04": {20: 24.0, 60: 8.0},
            "2024-01-05": {20: 21.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas, confirm=False)["sells"], 1)
        confirmed = self.run_case(states, mas, confirm=True)
        self.assertEqual(confirmed["sells"], 0)
        self.assertEqual(confirmed["stats"]["T+1确认·减持取消·价格线恢复"], 1)

    def test_swap_is_cancelled_when_same_source_recovers_above_ma20(self) -> None:
        # x=100% 让 H 在 D1 用尽资金。D2 的 X 触发 H→X 换仓，D3 H 恢复后取消原配对，
        # 不在 T+1 改选另一卖出源。
        states = {
            "2024-01-02": [row("H", 10.0, 20.0)],
            "2024-01-03": [row("H", 10.0, 20.0), row("X", 20.0, 10.0)],
            "2024-01-04": [row("H", 10.0, 8.0), row("X", 10.0, 20.0)],
            "2024-01-05": [row("H", 12.0, 8.0), row("X", 10.0, 20.0)],
        }
        mas = {
            "H": {
                "2024-01-02": {20: 9.0, 60: 8.0},
                "2024-01-03": {20: 9.0, 60: 8.0},
                "2024-01-04": {20: 11.0, 60: 8.0},
                "2024-01-05": {20: 11.5, 60: 8.0},
            },
            "X": {
                "2024-01-03": {20: 19.0, 60: 18.0},
                "2024-01-04": {20: 9.0, 60: 8.0},
                "2024-01-05": {20: 9.0, 60: 8.0},
            },
        }
        plain = self.run_case(states, mas, confirm=False, x=1.0, swap=True)
        self.assertEqual((plain["sells"], plain["buys"]), (1, 2))
        confirmed = self.run_case(states, mas, confirm=True, x=1.0, swap=True)
        self.assertEqual((confirmed["sells"], confirmed["buys"]), (0, 1))
        self.assertEqual(confirmed["stats"]["T+1确认·换仓取消·来源站回均线"], 1)


if __name__ == "__main__":
    unittest.main()
