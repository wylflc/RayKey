"""Cross-sectional buy fraction: timing, universe, ties, and unchanged execution rules."""
import math
import unittest
import backtest_valuation_strategy as bt


def row(code, pv, price=10.0):
    return code, price, price / pv, pv


def fixture(days, **extra):
    bt.DELISTED_LAST.clear()
    ledger = []
    prices = {c: {d: next(r[1] for r in rs if r[0] == c) for d, rs in days.items() if any(r[0] == c for r in rs)}
              for c in {r[0] for rs in days.values() for r in rs}}
    mas = extra.pop('mas', {c: {d: {20: 9., 60: 8.} for d in days} for c in prices})
    x = extra.pop('x', .05)
    result = bt.run('trend', x, days, prices, {}, mas, min(days), max(days), 100_000.,
                    width=-.0454, trend_tranche=True, trend_ma=(20, 60), exec_delay=1,
                    exec_price='close', stop_ma=60, stop_line='min_entry_current',
                    entry_below_ma60='ma60_stop', addon_trend='ma-only', ledger=ledger, **extra)
    return result, ledger


def buys(ledger):
    return [(r['date'], r['security_code']) for r in ledger if r['action'] == '买入']


class BuyFractionTest(unittest.TestCase):
    def test_floor_decimal_and_code_ties(self):
        selected, n = bt.top_fraction_candidates([row(f'{i:06d}', 1.) for i in range(100, 0, -1)], .29)
        self.assertEqual(n, 100)
        self.assertEqual([r[0] for r in selected], [f'{i:06d}' for i in range(1, 30)])
        self.assertEqual(bt.top_fraction_candidates([row('A', 1.)], .2), ([], 1))

    def test_invalid_observations_and_duplicate_guard(self):
        pool = [row('A', 1.), ('B', 10., 10., math.nan), ('C', None, 10., 1.),
                ('D', 0., 10., .1), ('E', 10., -10., -1.), ('F', 10., 10., math.inf)]
        self.assertEqual(bt.top_fraction_candidates(pool, 1), ([row('A', 1.)], 1))
        self.assertEqual(bt.top_fraction_candidates([], .2), ([], 0))
        with self.assertRaisesRegex(ValueError, '重复公司'):
            bt.top_fraction_candidates([row('A', .5), row('A', 1.)], .2)

    def test_percent_validation_and_conflict_guard(self):
        for q in (-.1, 20, math.nan, math.inf):
            with self.assertRaises(ValueError): bt.validate_buy_top_pct(q)
        bt.validate_buy_top_pct(0, gate=True)
        with self.assertRaisesRegex(ValueError, 'gate'):
            bt.validate_buy_top_pct(.2, gate=True)

    def test_default_off_is_identical(self):
        days = {d: [row('A', .8), row('B', 1.2)] for d in ('2024-01-02', '2024-01-03', '2024-01-04')}
        self.assertEqual(fixture(days), fixture(days, buy_top_pct=0))

    def test_ranking_uses_signal_date_and_replaces_fixed_line(self):
        days = {'2024-01-02': [row('A', 2.), row('B', 3.), row('C', 4.), row('D', 5.), row('E', 6.)],
                '2024-01-03': [row('A', 6.), row('B', 1.), row('C', 4.), row('D', 5.), row('E', 7.)],
                '2024-01-04': [row('A', 6.), row('B', 1.), row('C', 4.), row('D', 5.), row('E', 7.)]}
        res, ledger = fixture(days, buy_top_pct=.2)
        self.assertEqual(buys(ledger), [('2024-01-03', 'A'), ('2024-01-04', 'B')])
        self.assertFalse(any(r['action'] == '卖出' for r in ledger))
        self.assertEqual(res['stats']['横截面·分母公司日'], 10)
        self.assertEqual(res['stats']['横截面·排名选入公司日'], 2)

    def test_rank_precedes_trend_and_does_not_refill(self):
        days = {d: [row('A', .5), row('B', .6), row('C', .7), row('D', .8), row('E', .9)]
                for d in ('2024-01-02', '2024-01-03')}
        mas = {c: {d: {20: 11. if c == 'A' else 9., 60: 8.} for d in days} for c in 'ABCDE'}
        _, ledger = fixture(days, buy_top_pct=.2, mas=mas)
        self.assertEqual(buys(ledger), [])

    def test_future_entrant_not_in_signal_denominator(self):
        days = {d: [row('A', 2.), row('B', .1), row('C', 3.), row('D', 4.), row('E', 5.), row('F', 6.)]
                for d in ('2024-01-02', '2024-01-03', '2024-01-04')}
        universe = [('2024-01-02', set('ACDEF')), ('2024-01-03', set('ABCDEF'))]
        res, ledger = fixture(days, buy_top_pct=.2, universe=universe)
        self.assertEqual(buys(ledger), [('2024-01-03', 'A'), ('2024-01-04', 'B')])
        self.assertEqual(res['stats']['横截面·分母公司日'], 11)

    def test_execution_day_exit_blocks_fill_without_refill(self):
        days = {d: [row('A', .1), row('B', .2), row('C', .3), row('D', .4), row('E', .5)]
                for d in ('2024-01-02', '2024-01-03')}
        universe = [('2024-01-02', set('ABCDE')), ('2024-01-03', set('BCDE'))]
        res, ledger = fixture(days, buy_top_pct=.2, universe=universe)
        self.assertEqual(buys(ledger), [])
        self.assertEqual(res['stats']['横截面·排名选入公司日'], 1)
        self.assertEqual(res['stats']['横截面·成交日在册公司日'], 0)

    def test_winner_exclusion_recomputes_denominator(self):
        days = {d: [row('A', .1), row('B', .2), row('C', .3), row('D', .4), row('E', .5)]
                for d in ('2024-01-02', '2024-01-03')}
        res, ledger = fixture(days, buy_top_pct=.2, universe=[('2024-01-02', set('BCDE'))])
        self.assertEqual(res['stats']['横截面·分母公司日'], 4)
        self.assertEqual(buys(ledger), [])

    def test_swap_margin_remains_raw_pv(self):
        for later_b, expect_swap in ((.91, False), (.80, True)):
            days = {'2024-01-02': [row('A', .5), row('B', 1.2)],
                    '2024-01-03': [row('A', 1.), row('B', later_b)],
                    '2024-01-04': [row('A', 1.), row('B', later_b)]}
            mas = {c: {d: {20: 11. if c == 'A' and d != '2024-01-02' else 9., 60: 8.} for d in days}
                   for c in 'AB'}
            _, ledger = fixture(days, x=1., buy_top_pct=.5, mas=mas, swap=True,
                                swap_partial=True, swap_require_weak=True, swap_margin=.15)
            self.assertEqual(any(r['action'] == '卖出' for r in ledger), expect_swap)
            self.assertEqual(('2024-01-04', 'B') in buys(ledger), expect_swap)


if __name__ == '__main__': unittest.main()
