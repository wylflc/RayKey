"""Independent window and cash/share checks for actions without stock quotes."""
import datetime as dt
import math
import statistics as st
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'experimental'))
import backtest_valuation_strategy as bt
from moat_param_lab import total_return_index
from pv_episode_forward import return_indices


def rebase(value, start, end, events):
    for d, (cash, bonus, rights, subscription) in sorted(events.items()):
        if start < d <= end:
            value = (value - cash + rights * subscription) / (1 + bonus + rights)
    return value


class SuspendedActionsTest(unittest.TestCase):
    def setUp(self):
        self.days = [(dt.date(2020, 1, 1) + dt.timedelta(days=i)).isoformat()
                     for i in range(120) if i not in (15, 16, 45, 46, 47, 80)]
        self.prices = {d: 20 + .03 * i + math.sin(i / 7) for i, d in enumerate(self.days)}
        self.events = {'2019-12-01': (8, 1, 0, 0), '2020-01-01': (5, 1, 0, 0),
                       '2020-01-16': (1, .2, 0, 0), '2020-01-17': (.1, .1, .3, 4),
                       '2020-02-15': (.3, 0, .1, 5), '2020-02-17': (.5, .2, 0, 0),
                       '2020-03-21': (0, .5, 0, 0), '2020-04-29': (.2, 0, 0, 0),
                       '2020-06-01': (10, 2, .1, 1)}

    def test_affine_matches_sequential_events(self):
        scales, shifts = bt.exright_affine(self.days, self.events)
        for i, d in enumerate(self.days):
            self.assertAlmostEqual(scales[i] * self.prices[d] + shifts[i],
                                   rebase(self.prices[d], d, self.days[-1], self.events), places=11)

    def test_all_ma_windows_match_direct_same_day_basis(self):
        windows = (2, 20, 60)
        mas = bt.adjusted_moving_averages(self.prices, self.events, windows)
        for i, d in enumerate(self.days):
            for n in windows:
                if i + 1 >= n:
                    expected = st.mean(rebase(self.prices[p], p, d, self.events)
                                       for p in self.days[i-n+1:i+1])
                    self.assertAlmostEqual(mas[d][n], expected, places=10)

    def test_future_events_and_quotes_do_not_change_past_ma(self):
        n = 72
        prefix = {d: self.prices[d] for d in self.days[:n]}
        all_ma = bt.adjusted_moving_averages(self.prices, self.events, (20, 60))
        prefix_ma = bt.adjusted_moving_averages(prefix, self.events, (20, 60))
        for d, values in prefix_ma.items():
            for w, value in values.items():
                self.assertAlmostEqual(value, all_ma[d][w], places=10)

    def test_no_actions_is_identical(self):
        self.assertEqual(bt.adjusted_moving_averages(self.prices, {}), bt.moving_averages(self.prices))
        self.assertEqual(bt.adjusted_close_series(self.prices, {}), self.prices)
        self.assertEqual(total_return_index(list(self.prices.items()), []), self.prices)

    def test_quote_boundaries_and_empty(self):
        self.assertEqual(bt.exright_affine([], self.events), ([], []))
        self.assertEqual(list(bt.quote_action_factors([], self.events)), [])
        self.assertEqual(bt.adjusted_moving_averages({}, self.events), {})
        self.assertEqual(total_return_index([], []), {})
        self.assertEqual(bt.exright_affine(['2020-01-01'], self.events), ([1.0], [0.0]))
        self.assertEqual(list(bt.quote_action_factors(['2020-01-01'], self.events)), [(1.0, 0.0)])

    def test_volume_rebases_suspended_split(self):
        days = ['2020-01-01', '2020-01-02', '2020-01-06']
        volume = dict(zip(days, [100, 100, 200]))
        event = {'2020-01-04': (1, 1, 0, 0)}
        self.assertAlmostEqual(bt.volume_ratio_series(volume, event, 2)[days[-1]], 1)

    def test_multi_event_cash_and_rights_order(self):
        days = ['2020-01-01', '2020-01-06', '2020-01-07']
        prices = [30, 10, 12]
        events = {'2020-01-02': (2, 1, 0, 0), '2020-01-04': (3, .5, .2, 4)}
        # One share -> two; cash 2. Then cash += 2*(3-.2*4), shares *= 1.7.
        factors = list(bt.quote_action_factors(days, events))
        self.assertAlmostEqual(factors[1][0], 3.4)
        self.assertAlmostEqual(factors[1][1], 6.4)
        rows = [dict(ex_dividend_date=d, cash_per_share=str(c), share_ratio=str(b), rights_ratio=str(r), rights_price=str(p))
                for d, (c, b, r, p) in events.items()]
        result = total_return_index(list(zip(days, prices)), rows)
        self.assertAlmostEqual(result[days[1]], 40.4)
        self.assertAlmostEqual(result[days[2]], 48.48)
        returns = bt.daily_returns({'X': dict(zip(days, prices))}, {'X': events})['X']
        self.assertAlmostEqual(returns[days[1]], 40.4 / 30 - 1)
        tri, shares, cash = return_indices(days, prices, events)
        for i, d in enumerate(days):
            self.assertAlmostEqual(result[d] / result[days[0]], tri[i])
        self.assertAlmostEqual(shares[1], 3.4)
        self.assertAlmostEqual(cash[1], 6.4)

    def test_ex_day_event_is_not_reapplied_to_entry(self):
        dates = ['2020-01-02', '2020-01-03']
        acts = {'2020-01-02': (1, 1, .2, 4), '2020-02-01': (2, 2, 0, 0)}
        result = bt.daily_returns({'X': dict(zip(dates, [10, 11]))}, {'X': acts})['X']
        self.assertAlmostEqual(result[dates[-1]], .1)

    def test_action_delivery_does_not_require_stock_quote(self):
        lot = bt.Lot('X', '2020-01-01', .8, 12, 10, 14, .25)
        lot.shares = 100
        lot.entry_stop = 9
        pf = bt.Portfolio(cash=0)
        pf.lots['X'] = lot
        bt.apply_corporate_actions(pf, '2020-01-03', {'X': {'2020-01-03': (1, 1, 0, 0)}})
        self.assertEqual(pf.cash, 100)
        self.assertEqual(lot.shares, 200)
        self.assertEqual(lot.entry_stop, 4)


if __name__ == '__main__':
    unittest.main()
