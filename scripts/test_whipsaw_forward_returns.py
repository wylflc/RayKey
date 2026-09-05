"""Historical forward returns must exclude dividends beyond the horizon."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "experimental"))
from whipsaw_swap_diag import holding_return_path


class ForwardReturnTest(unittest.TestCase):
    def test_future_dividends_do_not_change_historical_return(self):
        prices = {"a": 3, "b": 3.3, "z": 0.1}
        actions = {"z": (2.9, 0, 0, 0)}
        self.assertAlmostEqual(holding_return_path(prices, actions, ["a", "b"])[-1], 0.1)

    def test_dividend_bonus_and_rights_are_self_financing(self):
        # One share worth 10 pays 1 cash, doubles shares and grants 0.5 rights at 2.
        # Ex-date price = (10 - 1 + 0.5*2) / 2.5 = 4; terminal wealth remains 10.
        self.assertEqual(holding_return_path({"a": 10, "b": 4}, {"b": (1, 1, 0.5, 2)}, ["a", "b"]), [0, 0])

    def test_entry_date_action_is_not_collected_twice(self):
        self.assertEqual(holding_return_path({"a": 9, "b": 9}, {"a": (1, 0, 0, 0)}, ["a", "b"]), [0, 0])

    def test_cash_dividend_is_retained_not_implicitly_reinvested(self):
        result = holding_return_path({"a": 10, "b": 9, "c": 18}, {"b": (1, 0, 0, 0)}, ["a", "b", "c"])
        self.assertAlmostEqual(result[-1], 0.9)

    def test_action_during_suspension_is_included(self):
        self.assertEqual(holding_return_path({"a": 10, "c": 5}, {"b": (0, 1, 0, 0)}, ["a", "c"]), [0, 0])


if __name__ == "__main__":
    unittest.main()
