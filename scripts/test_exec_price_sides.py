#!/usr/bin/env python3
"""`--exec-price` 三种取值下买卖成交价的回归测试：close／open／open_sell_close_buy。"""

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


class ExecPriceSidesTest(unittest.TestCase):
    # T 日（01-02）A 合格：P/V 0.83、收盘 > MA20 > MA60 → T+1（01-03）成交一档；
    # 01-03 信号 P/V 1.17 不合格（不加仓）；01-04 收盘 25 ≥ 均价 × 2.10 触发涨幅减持 → 01-05 成交卖出一档。
    STATES = {
        "2024-01-02": [row("A", 10.0, 12.0)],
        "2024-01-03": [row("A", 10.5, 9.0)],
        "2024-01-04": [row("A", 25.0, 12.0)],
        "2024-01-05": [row("A", 26.0, 12.0)],
        "2024-01-08": [row("A", 26.5, 12.0)],
    }
    OPENS = {"A": {"2024-01-03": 10.2, "2024-01-04": 24.0, "2024-01-05": 25.5, "2024-01-08": 26.2}}
    MAS = {"A": {d: {20: 9.0, 60: 8.0} for d in STATES}}

    def run_case(self, exec_price: str, exec_delay: int = 1):
        bt.DELISTED_LAST.clear()
        ledger: list = []
        bt.run(
            "trend", 0.05, self.STATES, market(self.STATES), {}, self.MAS,
            min(self.STATES), max(self.STATES), 100_000.0,
            width=0.0454, trend_tranche=True, trend_ma=(20, 60),
            exec_delay=exec_delay, exec_price=exec_price, opens=self.OPENS,
            stop_ma=60, stop_line="min_entry_current", entry_below_ma60="ma60_stop",
            addon_trend="ma-only", gain_sell=1.10, gain_sell_mode="ungated",
            lot_size=100, ledger=ledger,
        )
        return ledger

    def prices(self, ledger, action: str) -> list[float]:
        return [float(r["price"]) for r in ledger if r["action"] == action]

    def test_close_uses_t1_close_both_sides(self) -> None:
        ledger = self.run_case("close")
        self.assertEqual(self.prices(ledger, "买入"), [10.5])
        self.assertEqual(self.prices(ledger, "卖出")[:1], [26.0])

    def test_open_uses_t1_open_both_sides(self) -> None:
        ledger = self.run_case("open")
        self.assertEqual(self.prices(ledger, "买入"), [10.2])
        self.assertEqual(self.prices(ledger, "卖出")[:1], [25.5])

    def test_open_sell_close_buy_splits_sides(self) -> None:
        ledger = self.run_case("open_sell_close_buy")
        self.assertEqual(self.prices(ledger, "买入"), [10.5])   # 买入按 T+1 收盘
        self.assertEqual(self.prices(ledger, "卖出")[:1], [25.5])   # 卖出按 T+1 开盘

    def test_same_day_uses_signal_close(self) -> None:
        ledger = self.run_case("close", exec_delay=0)
        self.assertEqual(self.prices(ledger, "买入"), [10.0])
        self.assertEqual(self.prices(ledger, "卖出")[:1], [25.0])   # 01-04 收盘触发、当日收盘成交

    def test_label_tag(self) -> None:
        self.assertEqual(bt.EXEC_PRICE_TAG["open_sell_close_buy"], "oc")


if __name__ == "__main__":
    unittest.main()
