"""Deterministic native-engine counterexamples for the one-candidate restriction."""
import copy
import unittest
from unittest.mock import patch
import engine

bt = engine.bt
DAY = '2024-01-03'


def replay(repeat, shares=None, pv_b=1., cash=0., lot_size=1, native=False, extra=None):
    shares = shares or {'A': 2, 'B': 10, 'C': 88}
    pvs = {'A': 1.1, 'B': pv_b, 'C': .5, 'X': .8, 'Y': .99}
    rows = [(c, 10., 10./pv, pv) for c,pv in pvs.items()]
    states = {DAY: rows}
    ma = {c: {DAY: {20:11., 60:12.} if c in shares else {20:9., 60:8.}} for c in pvs}
    lots = {c: bt.Lot(c, '2023-01-02', pvs[c], 10./pvs[c], 8., 12., 0.,
                     shares=q, avg_cost=10., invested=q*10.) for c,q in shares.items()}
    portfolio = bt.Portfolio(cash=cash, lots=lots)
    ledger, traces = [], []
    if native:
        run = engine.NATIVE_RUN
    else:
        engine.install(repeat, lambda *args: traces.append(dict(zip(engine.TRACE_FIELDS,args))))
        run = bt.run
    kwargs = dict(trend_tranche=True, trend_ma=(20,60), swap=True, swap_partial=True,
                  swap_margin=.15, swap_require_weak=True, swap_gain_once=True,
                  swap_repeat='skip', lot_size=lot_size, trend_stop=False,
                  execution_consistency='signal', exec_delay=0, ledger=ledger)
    kwargs.update(extra or {})
    with patch.object(bt, 'Portfolio', return_value=portfolio), patch.object(bt, 'trade_fee', return_value=0), \
         patch.object(bt, 'DELISTED_LAST', {}):
        result = run('trend', .1, states, {c:{DAY:10.} for c in pvs}, {}, ma,
                     DAY, DAY, cash+sum(shares.values())*10., **kwargs)
    return result, ledger, traces


class RepeatCandidateTests(unittest.TestCase):
    def tearDown(self):
        bt.run = engine.NATIVE_RUN

    def test_short_first_sale_reuses_cheapest_candidate(self):
        base, _, old = replay(False)
        changed, _, new = replay(True)
        self.assertEqual([(x['target'],x['source']) for x in old], [('X','A')])
        self.assertEqual([(x['target'],x['source']) for x in new], [('X','A'),('X','B')])
        self.assertEqual([x['shares'] for x in new], [2,10])
        self.assertLess(new[0]['funds_after'],new[0]['buy_tranche'])
        self.assertGreaterEqual(new[1]['funds_after'],new[1]['buy_tranche'])
        self.assertEqual(changed['negative_cash_days'],0)

    def test_no_extra_sale_with_sufficient_initial_funds(self):
        self.assertEqual(replay(True,cash=1000)[2], [])

    def test_insufficient_margin_still_stops(self):
        self.assertEqual([x['source'] for x in replay(True,pv_b=.9)[2]], ['A'])

    def test_partial_source_never_sold_twice(self):
        events = replay(True,shares={'A':100,'B':2,'C':898})[2]
        self.assertEqual(len({x['source'] for x in events}),len(events))
        self.assertEqual(sum(x['source']=='A' for x in events),1)

    def test_failed_zero_lot_does_not_retry_forever(self):
        self.assertEqual(replay(True,lot_size=100)[2], [])

    def test_trace_only_baseline_matches_native(self):
        native = replay(False,native=True)
        instrumented = replay(False)
        self.assertEqual(native[:2],instrumented[:2])

    def test_repeated_iterator_advances_after_no_progress(self):
        progress = [0]
        iterator = engine.repeat_candidates(['X','Y'],lambda:progress[0])
        self.assertEqual(next(iterator),'X')
        progress[0]+=1
        self.assertEqual(next(iterator),'X')
        self.assertEqual(next(iterator),'Y')
        with self.assertRaises(StopIteration): next(iterator)


if __name__ == '__main__':
    unittest.main()
