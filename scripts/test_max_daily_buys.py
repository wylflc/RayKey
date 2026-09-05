#!/usr/bin/env python3
"""每日净买入笔数上限：真实成交、T+1 顺位、加仓与同日对冲。"""
import collections
import unittest

import backtest_valuation_strategy as bt
from test_t1_execution_confirmation import market, row


class MaxDailyBuysTest(unittest.TestCase):
    def run_case(self, states, cap=0, **extra):
        bt.DELISTED_LAST.clear()
        mas = {c: {d: {20: 9.0, 60: 8.0} for d in states}
               for c in market(states)}
        ledger = []
        opts = dict(width=0.0, trend_tranche=True, trend_ma=(20, 60),
                    exec_delay=1, exec_price="close", stop_ma=60,
                    entry_below_ma60="ma60_stop", addon_trend="ma-only",
                    max_daily_buys=cap, lot_size=100, ledger=ledger)
        opts.update(extra)
        result = bt.run("trend", 0.05, states, market(states), {}, mas,
                        min(states), max(states), 100_000.0, **opts)
        return result, ledger

    def test_limit_resets_each_execution_day_and_includes_addons(self):
        states = {f"2024-01-0{d}": [row(c, 10.0, v) for c, v in
                                    (("A", 30), ("B", 25), ("C", 20))]
                  for d in (2, 3, 4)}
        for cap in (1, 2, 3, 5):
            with self.subTest(cap=cap):
                result, ledger = self.run_case(states, cap)
                buys = [r for r in ledger if r["action"] == "买入"]
                self.assertEqual(collections.Counter(r["date"] for r in buys),
                                 {"2024-01-03": min(cap, 3), "2024-01-04": min(cap, 3)})
                self.assertEqual([r["security_code"] for r in buys],
                                 list("ABC"[:cap]) * 2)
                self.assertEqual(result["buys"], len(buys))
                self.assertTrue(any(r["reason"] == "定投加仓" for r in buys))
        self.assertEqual(self.run_case(states), self.run_case(states, 99))

    def test_missing_fill_does_not_use_a_slot(self):
        states = {"2024-01-02": [row("A", 10, 30), row("B", 10, 20)],
                  "2024-01-03": [row("B", 10, 20)]}
        result, ledger = self.run_case(states, 1)
        self.assertEqual(result["buys"], 1)
        self.assertEqual([r["security_code"] for r in ledger if r["action"] == "买入"], ["B"])

    def test_full_netting_does_not_use_a_slot(self):
        # A 建仓后涨幅减一档又符合加仓；完全对冲后名额应留给 B。
        states = {"2024-01-02": [row("A", 10, 30)],
                  "2024-01-03": [row("A", 11, 30), row("B", 10, 20)],
                  "2024-01-04": [row("A", 12, 30), row("B", 10, 20)],
                  "2024-01-05": [row("A", 12, 30), row("B", 10, 20)]}
        result, ledger = self.run_case(states, 1, gain_sell=0.00001,
                                       gain_sell_mode="ungated", net_same_day=True)
        self.assertGreater(result["stats"].get("同日买卖对冲", 0), 0)
        last_buys = [r["security_code"] for r in ledger
                    if r["action"] == "买入" and r["date"] == "2024-01-05"]
        self.assertEqual(last_buys, ["B"])

    def test_netting_still_occurs_after_limit_and_residual_buy_is_blocked(self):
        states = {"2024-01-02": [row("A", 10, 30)],
                  "2024-01-03": [row("A", 10, 30)],
                  "2024-01-04": [row("A", 12, 30), row("B", 10, 50)],
                  "2024-01-05": [row("A", 12, 30), row("B", 10, 50)]}
        result, ledger = self.run_case(states, 1, gain_sell=0.00001, sell_x=0.025,
                                       gain_sell_mode="ungated", net_same_day=True)
        self.assertGreater(result["stats"].get("同日买卖对冲", 0), 0)
        self.assertGreater(result["stats"].get("每日买入上限·跳过净买入", 0), 0)
        self.assertEqual([r["security_code"] for r in ledger
                          if r["action"] == "买入" and r["date"] == "2024-01-05"], ["B"])

    def test_negative_cap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            self.run_case({"2024-01-02": [row("A", 10, 20)]}, -1)


if __name__ == "__main__":
    unittest.main()
