"""Deterministic price paths for entry/current MA maximum stop semantics."""
import unittest
import backtest_valuation_strategy as bt


class StopLineMaxTest(unittest.TestCase):
    def run_path(self, current=10.0, mode="max_entry_current", basis="exec"):
        days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        closes = [12.0, 12.0, 9.0, 11.0]
        # Only the first day permits a buy, so stop outcomes cannot be hidden by a re-entry.
        states = {d: [("A", p, 20.0 if i == 0 else 1.0, p / (20.0 if i == 0 else 1.0))]
                  for i, (d, p) in enumerate(zip(days, closes))}
        mas = {"A": {d: {20: 11.0, 60: 8.0 if i < 2 else current}
                     for i, d in enumerate(days)}}
        ledger = []
        bt.DELISTED_LAST.clear()
        bt.run("trend", 0.5, states, {"A": dict(zip(days, closes))}, {}, mas,
               days[0], days[-1], 100_000.0, width=0.0, trend_tranche=True,
               trend_ma=(20, 60), exec_delay=1, exec_price="close", stop_ma=60,
               stop_line=mode, stop_basis=basis, entry_below_ma60="ma60_stop",
               lot_size=100, ledger=ledger)
        return [(r["date"], float(r["price"])) for r in ledger if r["action"] == "卖出" and "止损" in r["reason"]]

    def test_rising_ma_stops_at_exec_day_price(self):
        self.assertEqual(self.run_path(), [("2024-01-04", 9.0)])
        self.assertEqual(self.run_path(mode="min_entry_current"), [])
        self.assertEqual(self.run_path(mode="entry"), [])

    def test_signal_and_both_use_signal_day_ma(self):
        self.assertEqual(self.run_path(basis="signal"), [("2024-01-05", 11.0)])
        self.assertEqual(self.run_path(basis="both"), [("2024-01-04", 9.0)])

    def test_falling_ma_cannot_lower_stop_below_entry(self):
        self.assertEqual(bt.effective_stop_level(10, 8, "max_entry_current"), 10)
        self.assertEqual(bt.effective_stop_level(10, 8, "min_entry_current"), 8)

    def test_missing_ma_preserves_entry_anchor(self):
        self.assertEqual(bt.effective_stop_level(10, 0, "max_entry_current"), 10)
        self.assertEqual(bt.effective_stop_level(0, 10, "max_entry_current"), 0)
        self.assertEqual(self.run_path(current=0), [])

    def test_no_high_water_mark_and_equal_price_does_not_trigger(self):
        levels = [bt.effective_stop_level(8, ma, "max_entry_current") for ma in (10, 12, 9, 7)]
        self.assertEqual(levels, [10, 12, 9, 8])
        self.assertEqual(bt.update_stop_breach(9, levels[2], 0), (0, ""))


if __name__ == "__main__":
    unittest.main()
