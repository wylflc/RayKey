"""Boundary, hysteresis, and causal-history checks independent of portfolio results."""
import unittest
from datetime import date
from policy import compute_caps, grid, ResearchConstraint, ROOT
from equity_bond_constraint import EquityBondSignal, EquityBondConstraint


def example(spreads, kind='hysteresis', **spec):
    signals = [EquityBondSignal(f'2020-{i+1:02}-28', s, None, i) for i,s in enumerate(spreads)]
    rows = [dict(observed_on=s.observed_on, pe=16, pe_q=.8, index_close=120,
                 ma60=100, ma6=125, ma10=110, ma12=110) for s in signals]
    return compute_caps(signals, rows, dict(kind=kind, **spec))[0]


class PolicyTest(unittest.TestCase):
    def test_hysteresis_and_ties(self):
        self.assertEqual(example([.035,.029,.03,.039,.04,.03,.028], cap=.3, release=.04),
                         [None,.3,.3,.3,None,None,.3])

    def test_zero_cap_is_not_missing(self):
        self.assertEqual(example([.02,.03], cap=0., release=.03), [0.,None])

    def test_consecutive_months_reset(self):
        self.assertEqual(example([.02,.03,.02,.03,.04], kind='confirm', months=2),
                         [1.,1.,1.,1.,None])

    def test_trend_only_affects_recovery(self):
        self.assertEqual(example([.04,.02,.04], kind='trend', ma=6), [None,1.,1.])
        self.assertEqual(example([.04,.02,.04], kind='trend', ma=10), [None,1.,None])

    def test_absolute_and_relative_price(self):
        self.assertEqual(example([.02,.04], kind='pe', threshold=16), [1.,1.])
        self.assertEqual(example([.02,.04], kind='price_ma', threshold=1.2), [1.,1.])

    def test_current_base_equivalent_and_query_order(self):
        p = ROOT/'data/reference/equity_bond_csi300.csv'
        kw = dict(mode='cap', metric='spread', threshold=.03, lower=1., restore_above=True)
        old = EquityBondConstraint(p, **kw)
        candidate = ResearchConstraint(p, **kw, spec=dict(kind='hysteresis', cap=1., release=.03))
        for day in reversed(old.days):
            self.assertEqual(old.resolve(day), candidate.resolve(day))
        with self.assertRaisesRegex(ValueError, 'Stale'):
            candidate.resolve('2027-01-01')
        self.assertEqual(candidate.resolve('2000-01-01'), (None,None))

    def test_prefix_causality_and_warmup(self):
        p = ROOT/'data/reference/equity_bond_csi300.csv'
        for spec in grid():
            c = ResearchConstraint(p, mode='cap', metric='spread', threshold=.03,
                                   lower=1., restore_above=True, spec=spec)
            for n in (24,100,150):
                prefix, _ = compute_caps(c.signals[:n], c.rows[:n], spec)
                self.assertEqual(prefix, c.caps[:n], spec)
            for f in c.rows:
                self.assertLessEqual(f['index_day'], f['observed_on'])
            if spec['kind'] == 'price_ma':
                self.assertTrue(c.audit[0]['fallback'])
                first = next(f for f in c.audit if not f['fallback'])
                self.assertEqual(first['observed_on'][:7], '2009-12')


if __name__ == '__main__':
    unittest.main()
