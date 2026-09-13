#!/usr/bin/env python3
"""OI-167：回测引擎的单票上限与整手兜底（§9.3.1「不足一手跳过」、§9.3.1.1）——上限余量不足一手时不得经高价股一手兜底越限。
合成路径沿用 `data/experiments/exp_position_cap_25_20260908/test_strict_cap.py` 的四种情形，对象改为正式引擎。"""
from datetime import date, timedelta
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_valuation_strategy as bt  # noqa: E402


def path(prices, capital, position_cap=.25, lot_size=100):
    days = [(date(2024, 1, 2) + timedelta(days=i)).isoformat() for i in range(len(prices))]
    states = {day: [("A", price, price * 2, .5)] for day, price in zip(days, prices)}
    quotes = {"A": dict(zip(days, prices))}
    mas = {"A": {day: {20: price * .9, 60: price * .8} for day, price in zip(days, prices)}}
    ledger = []
    result = bt.run("trend", .05, states, quotes, {}, mas, days[0], days[-1], capital,
                    trend_tranche=True, trend_ma=(20, 60), exec_delay=1, lot_size=lot_size,
                    lot_ratio_cooldown=True, position_cap=position_cap, ledger=ledger)
    return ledger, result


def bought(rows):
    return sum(float(r["shares"]) * float(r["price"]) for r in rows if r["action"] == "买入")


class PositionCapLotTest(unittest.TestCase):
    def test_one_lot_cannot_bypass_cap(self):
        # 净资产 3,000、25% 上限 = 750 < 一手 1,000：一手兜底不得成交
        ledger, result = path([10] * 4, 3000)
        self.assertFalse(any(r["action"] == "买入" for r in ledger))
        self.assertGreater(result["stats"]["单股上限·余量不足一手·跳过"], 0)

    def test_one_lot_above_tranche_but_below_cap_is_allowed(self):
        # 一档 500 < 一手 1,000 ≤ 上限余量 2,500：高价股按手建仓照常
        ledger, result = path([10] * 2, 10000)
        self.assertEqual(sum(float(r["shares"]) for r in ledger if r["action"] == "买入"), 100)
        self.assertGreater(result["stats"]["高价股·按手建仓"], 0)

    def test_room_below_one_lot_blocks_addition(self):
        # 净资产 18,000、上限 4,500：一档 900 买不起一手，兜底逐手加到 4,000 后余量 500 < 一手，停在 4,000（原实现会到 5,000）
        ledger, _ = path([10] * 10, 18000)
        self.assertEqual(bought(ledger), 4000)

    def test_no_cap_keeps_lot_fallback(self):
        ledger, _ = path([10] * 10, 18000, position_cap=0.0)
        self.assertGreater(bought(ledger), 4500)

    def test_passive_overshoot_does_not_sell(self):
        ledger, _ = path([10] * 7 + [12] * 3, 20000)
        self.assertFalse(any(r["action"] == "卖出" for r in ledger))
        shares = sum(float(r["shares"]) for r in ledger if r["action"] == "买入")
        self.assertEqual(shares, 500)
        self.assertGreater(shares * 12 / (20000 + shares * 2), .25)


if __name__ == "__main__":
    unittest.main()
