#!/usr/bin/env python3
"""卖侧 T+1 走势复核（--sell-confirm）、卖侧容差（--sell-tol）、止损容差（--stop-tol）与 summary 前五赢家列的回归测试。"""

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


class SellConfirmationTest(unittest.TestCase):
    def run_case(self, states, mas, *, x: float = 0.05, swap: bool = False,
                 sell_confirm: bool = False, sell_tol: float = 0.0,
                 stop_tol: float = 0.0, stop_confirm_days: int = 1):
        bt.DELISTED_LAST.clear()
        return bt.run(
            "trend", x, states, market(states), {}, mas,
            min(states), max(states), 100_000.0,
            width=0.0657, trend_tranche=True, trend_ma=(20, 60),
            exec_delay=1, exec_price="close", sell_trend_ma=(20,),
            sell_line_override=2.4257, stop_ma=60,
            stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.25, gain_sell_mode="gated",
            swap=swap, swap_margin=0.1437, swap_partial=True,
            swap_require_weak=True, swap_weak_ma=20,
            sell_confirm=sell_confirm, sell_tol=sell_tol, stop_tol=stop_tol,
            stop_confirm_days=stop_confirm_days,
        )

    # D0 信号 D1 建仓；D2 收盘「贵且弱」发减持信号；D3 为成交日。
    TRIM_STATES = {
        "2024-01-02": [row("A", 10.0, 20.0)],
        "2024-01-03": [row("A", 10.0, 20.0)],
        "2024-01-04": [row("A", 10.0, 4.0)],
    }
    TRIM_MAS = {
        "2024-01-02": {20: 9.0, 60: 8.0},
        "2024-01-03": {20: 9.0, 60: 8.0},
        "2024-01-04": {20: 11.0, 60: 8.0},
    }

    def test_trim_is_cancelled_when_t1_close_recovers_above_ma20(self) -> None:
        states = {**self.TRIM_STATES, "2024-01-05": [row("A", 12.0, 100.0)]}
        mas = {"A": {**self.TRIM_MAS, "2024-01-05": {20: 11.5, 60: 8.0}}}
        self.assertEqual(self.run_case(states, mas)["sells"], 1)
        confirmed = self.run_case(states, mas, sell_confirm=True)
        self.assertEqual(confirmed["sells"], 0)
        self.assertEqual(confirmed["stats"]["卖出T+1确认·减持取消·收盘站回均线"], 1)

    def test_trim_keeps_signal_day_value_trigger_when_t1_still_weak(self) -> None:
        # T+1 只复核走势：P/V 在 T+1 跌回买线之下也照减，因为收盘仍在 MA20 之下。
        states = {**self.TRIM_STATES, "2024-01-05": [row("A", 9.0, 100.0)]}
        mas = {"A": {**self.TRIM_MAS, "2024-01-05": {20: 11.5, 60: 8.0}}}
        confirmed = self.run_case(states, mas, sell_confirm=True)
        self.assertEqual(confirmed["sells"], 1)
        self.assertNotIn("卖出T+1确认·减持取消·收盘站回均线", confirmed["stats"])

    def test_trim_confirmation_requires_t1_ma(self) -> None:
        states = {**self.TRIM_STATES, "2024-01-05": [row("A", 9.0, 100.0)]}
        mas = {"A": {**self.TRIM_MAS, "2024-01-05": {60: 8.0}}}
        confirmed = self.run_case(states, mas, sell_confirm=True)
        self.assertEqual(confirmed["sells"], 0)
        self.assertEqual(confirmed["stats"]["卖出T+1确认·减持取消·均线缺失"], 1)

    def test_sell_tolerance_widens_weakness_line(self) -> None:
        # 信号日收盘 10.9 < MA20 11.0，但 ≥ 11.0×0.98=10.78：2% 容差下不算弱势。
        states = {
            "2024-01-02": [row("A", 10.0, 20.0)],
            "2024-01-03": [row("A", 10.0, 20.0)],
            "2024-01-04": [row("A", 10.9, 4.0)],
            "2024-01-05": [row("A", 10.9, 100.0)],
        }
        mas = {"A": {
            "2024-01-02": {20: 9.0, 60: 8.0},
            "2024-01-03": {20: 9.0, 60: 8.0},
            "2024-01-04": {20: 11.0, 60: 8.0},
            "2024-01-05": {20: 11.0, 60: 8.0},
        }}
        self.assertEqual(self.run_case(states, mas)["sells"], 1)
        widened = self.run_case(states, mas, sell_tol=0.02)
        self.assertEqual(widened["sells"], 0)
        self.assertEqual(widened["stats"]["减持被走势闸门挡下"], 1)

    def test_sell_tolerance_one_percent_boundary(self) -> None:
        # 10.9 对 11.0×0.99=10.89：10.9 ≥ 10.89 → 1% 容差也挡下。
        states = {
            "2024-01-02": [row("A", 10.0, 20.0)],
            "2024-01-03": [row("A", 10.0, 20.0)],
            "2024-01-04": [row("A", 10.9, 4.0)],
            "2024-01-05": [row("A", 10.9, 100.0)],
        }
        mas = {"A": {d: {20: 11.0 if d >= "2024-01-04" else 9.0, 60: 8.0} for d in states}}
        self.assertEqual(self.run_case(states, mas, sell_tol=0.01)["sells"], 0)

    def test_swap_is_cancelled_when_source_recovers_above_ma20_on_t1(self) -> None:
        # x=100% 让 H 在 D1 用尽资金；D2 的 X 触发 H→X 换仓；D3 H 收盘站回 MA20 → 取消换仓。
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
        plain = self.run_case(states, mas, x=1.0, swap=True)
        self.assertEqual((plain["sells"], plain["buys"]), (1, 2))
        confirmed = self.run_case(states, mas, x=1.0, swap=True, sell_confirm=True)
        self.assertEqual((confirmed["sells"], confirmed["buys"]), (0, 1))
        self.assertEqual(confirmed["stats"]["卖出T+1确认·换仓取消·来源站回均线"], 1)

    def test_swap_source_weakness_uses_sell_tolerance(self) -> None:
        # 信号日 H 收盘 10.9 < MA20 11.0 但 ≥ 11.0×0.98：2% 容差下 H 不算弱势，不能作换仓来源。
        states = {
            "2024-01-02": [row("H", 10.0, 20.0)],
            "2024-01-03": [row("H", 10.0, 20.0), row("X", 20.0, 10.0)],
            "2024-01-04": [row("H", 10.9, 8.0), row("X", 10.0, 20.0)],
            "2024-01-05": [row("H", 10.9, 8.0), row("X", 10.0, 20.0)],
        }
        mas = {
            "H": {d: {20: 11.0 if d >= "2024-01-04" else 9.0, 60: 8.0} for d in states},
            "X": {"2024-01-03": {20: 19.0, 60: 18.0}, "2024-01-04": {20: 9.0, 60: 8.0},
                  "2024-01-05": {20: 9.0, 60: 8.0}},
        }
        self.assertEqual(self.run_case(states, mas, x=1.0, swap=True)["sells"], 1)
        self.assertEqual(self.run_case(states, mas, x=1.0, swap=True, sell_tol=0.02)["sells"], 0)

    # D0 信号 D1 建仓（成交日 MA60 = 8 为锚）；D2 收盘 7.9 跌破生效线 min(8, 8)。
    STOP_STATES = {
        "2024-01-02": [row("A", 10.0, 20.0)],
        "2024-01-03": [row("A", 10.0, 5.0)],
        "2024-01-04": [row("A", 7.9, 20.0)],
    }
    STOP_MAS = {d: {20: 9.0, 60: 8.0} for d in ("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05")}

    def test_stop_tolerance_moves_effective_line_down(self) -> None:
        states = {**self.STOP_STATES, "2024-01-05": [row("A", 7.9, 20.0)]}
        mas = {"A": self.STOP_MAS}
        self.assertEqual(self.run_case(states, mas)["sells"], 1)
        self.assertEqual(self.run_case(states, mas, stop_tol=0.01)["sells"], 1)   # 7.9 < 8×0.99=7.92
        self.assertEqual(self.run_case(states, mas, stop_tol=0.02)["sells"], 0)   # 7.9 ≥ 8×0.98=7.84

    def test_stop_t1_confirmation_is_two_consecutive_breaches(self) -> None:
        # --stop-confirm-days 2：单日跌破不触发，T+1 仍跌破才在 T+1 清仓；T+1 站回线上即清零。
        breach_twice = {**self.STOP_STATES, "2024-01-05": [row("A", 7.9, 20.0)]}
        recover = {**self.STOP_STATES, "2024-01-05": [row("A", 8.2, 20.0)]}
        mas = {"A": self.STOP_MAS}
        self.assertEqual(self.run_case(breach_twice, mas, stop_confirm_days=2)["sells"], 1)
        self.assertEqual(self.run_case(recover, mas, stop_confirm_days=2)["sells"], 0)
        self.assertEqual(self.run_case(self.STOP_STATES, {"A": self.STOP_MAS}, stop_confirm_days=2)["sells"], 0)

    def test_summary_reports_top5_winners_by_code(self) -> None:
        states = {
            "2024-01-02": [row("A", 10.0, 20.0), row("B", 10.0, 20.0)],
            "2024-01-03": [row("A", 10.0, 20.0), row("B", 10.0, 20.0)],
            "2024-01-04": [row("A", 15.0, 20.0), row("B", 9.0, 20.0)],
        }
        mas = {c: {d: {20: 9.0, 60: 8.0} for d in states} for c in ("A", "B")}
        result = self.run_case(states, mas)
        summary = bt.summarize("t", result, 100_000.0, {}, [])
        self.assertEqual(summary["前五赢家"], "A")          # 只列盈利为正的代码，B 亏损不入列
        self.assertGreater(summary["前五赢家盈亏"], 0)
        self.assertAlmostEqual(summary["前五赢家占正贡献"], 1.0)


if __name__ == "__main__":
    unittest.main()
