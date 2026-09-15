"""Boundary and denominator checks for independent startup return reporting."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'experimental'))
from startup_horizon_returns import add_months, measure, period_end, quantile


def nav(day, equity, positions=0, debt=0):
    return dict(date=day, net_equity=equity, positions=positions, debt=debt)


class StartupReturnsTests(unittest.TestCase):
    def test_calendar_months_and_leap_year(self):
        self.assertEqual(period_end('2020-01-01', 3), '2020-03-31')
        self.assertEqual(period_end('2020-02-01', 1), '2020-02-29')
        self.assertEqual(add_months('2020-02-01', 36), '2023-02-01')
        with self.assertRaises(ValueError):
            add_months('2020-02-15', 1)

    def test_initial_cash_denominator_and_month_end_weekend(self):
        days = ['2020-02-03', '2020-02-04', '2020-02-28']
        curve = [nav(days[0], 100), nav(days[1], 99, 1), nav(days[2], 120, 1)]
        r = measure(curve, '2020-02-01', 1, '2020-03-02', 100, days)
        self.assertAlmostEqual(r['cumulative_return'], .2)
        self.assertAlmostEqual(r['max_drawdown'], .01)
        self.assertEqual(r['end_date'], '2020-02-28')
        self.assertEqual(r['first_trade_date'], '2020-02-04')

    def test_incomplete_horizon_is_missing(self):
        curve = [nav('2020-02-03', 100), nav('2020-02-07', 110, 1)]
        r = measure(curve, '2020-02-01', 1, '2020-02-07', 100, [r['date'] for r in curve])
        self.assertEqual(r['status'], 'insufficient_followup')
        self.assertEqual(r['cumulative_return'], '')

    def test_missing_terminal_nav_rejected(self):
        with self.assertRaises(ValueError):
            measure([nav('2020-02-03', 100)], '2020-02-01', 1, '2020-03-01',
                    100, ['2020-02-03', '2020-02-28'])

    def test_inherited_holdings_rejected(self):
        with self.assertRaises(ValueError):
            measure([nav('2020-02-03', 100, 1)], '2020-02-01', 1, '2020-03-01',
                    100, ['2020-02-03'])

    def test_future_nav_excluded_and_cash_only_retained(self):
        curve = [nav('2020-02-03', 100), nav('2020-02-28', 100), nav('2020-03-02', 1000, 1)]
        r = measure(curve, '2020-02-01', 1, '2020-03-02', 100, [r['date'] for r in curve])
        self.assertEqual(r['cumulative_return'], 0)
        self.assertEqual(r['first_trade_date'], '')

    def test_quantiles_interpolate(self):
        self.assertEqual(quantile([0, 1, 2, 3, 4], .25), 1)
        self.assertEqual(quantile([10, 0], .25), 2.5)


if __name__ == '__main__':
    unittest.main()
