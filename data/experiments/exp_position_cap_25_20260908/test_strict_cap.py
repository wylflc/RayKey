"""Small synthetic paths: capped buying, permitted large lots, passive overshoot."""
from datetime import date, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import backtest_valuation_strategy as bt
original_run = bt.run
sys.argv.append("--cap-lot-guard")
import strict_cap_engine as guarded


def path(prices, capital, strict):
    days = [(date(2024, 1, 2) + timedelta(days=i)).isoformat() for i in range(len(prices))]
    states = {day: [("A", price, price * 2, .5)] for day, price in zip(days, prices)}
    quotes = {"A": dict(zip(days, prices))}
    mas = {"A": {day: {20: price * .9, 60: price * .8} for day, price in zip(days, prices)}}
    ledger = []
    result = (guarded.guarded_run if strict else original_run)(
        "trend", .05, states, quotes, {}, mas, days[0], days[-1], capital,
        trend_tranche=True, trend_ma=(20, 60), exec_delay=1, lot_size=100,
        lot_ratio_cooldown=True, position_cap=.25, ledger=ledger)
    return ledger, result


class StrictCapTest(unittest.TestCase):
    def test_one_lot_cannot_bypass_cap(self):
        normal, _ = path([10] * 4, 3000, False)
        strict, result = path([10] * 4, 3000, True)
        self.assertTrue(any(row["action"] == "买入" for row in normal))
        self.assertFalse(any(row["action"] == "买入" for row in strict))
        self.assertGreater(result["stats"]["单股上限·余量不足一手"], 0)

    def test_one_lot_above_tranche_but_below_cap_is_allowed(self):
        strict, _ = path([10] * 2, 10000, True)
        self.assertEqual(sum(float(row["shares"]) for row in strict if row["action"] == "买入"), 100)

    def test_room_below_one_lot_blocks_addition(self):
        strict, _ = path([10] * 10, 18000, True)
        normal, _ = path([10] * 10, 18000, False)
        buy_value = lambda rows: sum(float(row["shares"]) * float(row["price"])
                                      for row in rows if row["action"] == "买入")
        self.assertLessEqual(buy_value(strict), 4500)
        self.assertGreater(buy_value(normal), 4500)

    def test_passive_overshoot_does_not_sell(self):
        strict, _ = path([10] * 7 + [12] * 3, 20000, True)
        self.assertFalse(any(row["action"] == "卖出" for row in strict))
        shares = sum(float(row["shares"]) for row in strict if row["action"] == "买入")
        self.assertEqual(shares, 500)
        self.assertGreater(shares * 12 / (20000 + shares * 2), .25)


if __name__ == "__main__":
    unittest.main()
