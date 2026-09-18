"""Seeded shadow-account accounting and point-in-time execution counterexamples."""
import copy
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import backtest_valuation_strategy as bt
import shadow_portfolio as shadow


def fixture(days=('2024-01-05', '2024-01-08')):
    lot = bt.Lot('A', '2023-01-01', 2., 50., 45., 55., -.5,
                 shares=1000., invested=100000., avg_cost=100., entry_stop=90., entry_stop_ma=60)
    seed = bt.Portfolio(cash=0., debt=20000., lots={'A': lot})
    return dict(strategy='trend', x=.05, states={d: [('A', 100., 50., 2.)] for d in days},
                prices={'A': {d: 100. for d in days}}, mas={'A': {d: {20: 101., 60: 95.} for d in days}},
                actions={}, since=days[0], until=days[-1], capital=80000., initial_portfolio=seed,
                exec_delay=1, lot_size=100, trend_tranche=True, trend_ma=(20, 60),
                liquidate_at_end=False, margin_rate=.035, credit_ratio=.666, credit_cap=1e9)


class ShadowSeedTests(unittest.TestCase):
    def setUp(self):
        self.fees = patch.dict(bt.FEES, commission=0., min_fee=0., transfer=0., stamp=0., stamp_mode='flat', paid=0.)
        self.fees.start()
        self.addCleanup(self.fees.stop)
        self.delisted = patch.object(bt, 'DELISTED_LAST', {})
        self.delisted.start()
        self.addCleanup(self.delisted.stop)

    def test_seed_mark_and_natural_day_interest_without_mutating_input(self):
        kw, states = fixture(), []
        original = copy.deepcopy(kw['initial_portfolio'])
        result = bt.run(**kw, portfolio_snapshots=states)
        self.assertEqual(result['equity'][0][1], 80000.)
        self.assertEqual(result['equity'][0][3], 1)
        self.assertEqual(result['closed'], [])
        self.assertAlmostEqual(result['interest_paid'], 20000 * .035 * 3 / 365)
        self.assertEqual(kw['initial_portfolio'], original)
        self.assertEqual(len(states), 2)
        self.assertEqual(states[-1]['holdings']['A']['stop'], 90.)

    def test_baseline_action_is_not_paid_twice(self):
        kw = fixture()
        kw['actions'] = {'A': {kw['since']: (1., 0., 0., 0.)}}
        result = bt.run(**kw)
        self.assertAlmostEqual(result['equity'][-1][1], 80000 - result['interest_paid'])

    def test_later_cash_dividend_and_price_drop_preserve_equity(self):
        kw = fixture()
        kw['margin_rate'] = 0.
        kw['prices']['A'][kw['until']] = 99.
        kw['states'][kw['until']] = [('A', 99., 50., 1.98)]
        kw['actions'] = {'A': {kw['until']: (1., 0., 0., 0.)}}
        observed = []
        result = bt.run(**kw, portfolio_snapshots=observed)
        self.assertEqual(result['equity'][-1][1], 80000.)
        self.assertEqual(observed[-1]['holdings']['A']['stop'], 89.)

    def test_seed_missing_price_and_wrong_capital_are_rejected(self):
        kw = fixture()
        del kw['prices']['A'][kw['since']]
        with self.assertRaisesRegex(ValueError, 'Missing closing price'):
            bt.run(**kw)
        kw = fixture(); kw['capital'] = 100000.
        with self.assertRaisesRegex(ValueError, 'differs from starting capital'):
            bt.run(**kw)

    def test_inherited_stop_executes_on_execution_day(self):
        kw = fixture()
        kw['prices']['A'][kw['until']] = 89.
        kw['states'][kw['until']] = [('A', 89., 50., 1.78)]
        kw.update(stop_line='min_entry_current', stop_ma=60, stop_basis='exec')
        ledger, observed = [], []
        bt.run(**kw, ledger=ledger, portfolio_snapshots=observed)
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]['date'], kw['until'])
        self.assertEqual(float(ledger[0]['shares']), 1000.)
        self.assertEqual(observed[-1]['holdings'], {})

    def test_buy_gate_is_signal_dated_and_does_not_force_exit(self):
        days = ('2024-01-05', '2024-01-08', '2024-01-09')
        kw = fixture(days)
        kw['initial_portfolio'] = bt.Portfolio(cash=80000.)
        kw['prices'] = {'A': {d: 10. for d in days}}
        kw['states'] = {d: [('A', 10., 20., .5)] for d in days}
        kw['mas'] = {'A': {d: {20: 9., 60: 8.} for d in days}}
        kw['buy_blocked'] = {days[0]: {'A'}, days[1]: set(), days[2]: {'A'}}
        ledger = []
        bt.run(**kw, ledger=ledger)
        self.assertEqual([r['date'] for r in ledger], [days[2]])
        kw = fixture()
        kw['buy_blocked'] = {kw['since']: {'A'}, kw['until']: {'A'}}
        observed = []
        bt.run(**kw, portfolio_snapshots=observed)
        self.assertEqual(observed[-1]['holdings']['A']['shares'], 1000.)

    def test_missing_gate_day_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing point-in-time buy gates'):
            bt.run(**fixture(), buy_blocked={})

    def test_future_prices_cannot_change_existing_path(self):
        days = ('2024-01-05', '2024-01-08', '2024-01-09')
        kw = fixture(days)
        before = bt.run(**kw)['equity']
        kw['prices']['A'][days[-1]] = 1000.
        kw['states'][days[-1]] = [('A', 1000., 50., 20.)]
        after = bt.run(**kw)['equity']
        self.assertEqual(before[:-1], after[:-1])

    def test_independent_fill_identity_detects_missing_execution(self):
        previous = {'A': {'shares': 100.}}
        current = {'A': {'shares': 200.}}
        q0, q1 = {'A': {'close': 10.}}, {'A': {'close': 12.}}
        fills = [dict(security_code='A', shares=100., price=11., side='buy')]
        self.assertEqual(shadow.economics(previous, current, q0, q1, fills, {}), (200., 100.))
        with self.assertRaisesRegex(ValueError, 'do not reconcile'):
            shadow.economics(previous, current, q0, q1, [], {})

    def test_archived_receipt_arithmetic_is_explicitly_flagged(self):
        snapshot = shadow.capture_snapshot('2026-09-17', shadow.Source('66326558'), shadow.sweep.BASE)
        discrepancy = snapshot['trade_amount_discrepancies']
        self.assertEqual(len(discrepancy), 1)
        self.assertAlmostEqual(discrepancy[0]['recorded_minus_calculated'], 96.)
        self.assertAlmostEqual(discrepancy[0]['shares_times_price'], 131328.)

    def test_base_changes_require_explicit_adapter_support(self):
        kwargs = shadow.engine_kwargs(shadow.sweep.BASE)
        self.assertEqual(kwargs['x'], .05)
        self.assertEqual(kwargs['trend_ma'], (20, 60))
        with self.assertRaisesRegex(ValueError, 'Unsupported BASE option'):
            shadow.engine_kwargs(shadow.sweep.BASE + ' --new-risk-mode something')

    def test_incomplete_path_is_not_silently_truncated(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete shadow path'):
            shadow.compare([{}], {'equity': []}, [], [])

    def test_snapshot_tampering_and_code_drift_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp)
            snapshot = dict(date='2026-09-18', actual_strategy_epoch='E4',
                            available_account_dates=['2026-09-18'])
            path = book / 'snapshots/2026-09-18.json'
            shadow.save(path, snapshot)
            protocol = dict(code_sha256=shadow.code_hashes(), base=shadow.sweep.BASE,
                            baseline_date=snapshot['date'], strategy_epoch='E4',
                            snapshots={snapshot['date']: shadow.sha(path.read_bytes())})
            shadow.save(book / 'protocol.json', protocol)
            shadow.load_book(book)
            path.write_text(path.read_text() + ' ')
            with self.assertRaisesRegex(ValueError, 'Archived snapshot changed'):
                shadow.load_book(book)
            protocol['code_sha256'] = {}
            shadow.save(book / 'protocol.json', protocol)
            with self.assertRaisesRegex(ValueError, 'Frozen code/BASE changed'):
                shadow.load_book(book)

    def test_unseeded_path_matches_prior_engine(self):
        # Compare the production default path with the pre-change engine, including
        # fees and terminal accounting; no seed/gate/snapshot options are used.
        old_source = subprocess.check_output(['git', 'show', 'a6759e5a:scripts/backtest_valuation_strategy.py'],
                                             cwd=shadow.ROOT, text=True)
        module = types.ModuleType('_shadow_old_engine')
        module.__file__ = str(shadow.ROOT / 'scripts/backtest_valuation_strategy.py')
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__)
        exec(compile(old_source, module.__file__, 'exec'), module.__dict__)
        days = ('2024-01-05', '2024-01-08', '2024-01-09')
        states = {d: [('A', p, 20., p / 20)] for d, p in zip(days, (10., 12., 8.))}
        prices = {'A': dict(zip(days, (10., 12., 8.)))}
        mas = {'A': {d: {20: 9., 60: 8.5} for d in days}}
        results = []
        for engine in (module, bt):
            engine.FEES.update(commission=.0001, min_fee=5., transfer=.00001, stamp=.0005, stamp_mode='flat', paid=0.)
            ledger = []
            result = engine.run('trend', .05, states, prices, {}, mas, days[0], days[-1], 100000.,
                trend_tranche=True, trend_ma=(20, 60), exec_delay=1, lot_size=100,
                stop_ma=60, stop_line='min_entry_current', ledger=ledger,
                credit_ratio=.666, credit_cap=1e9, margin_rate=.035)
            del result['closed']  # dataclass module identities differ, accounting fields remain checked
            results.append(json.dumps([result, ledger], sort_keys=True))
        self.assertEqual(results[0], results[1])


if __name__ == '__main__':
    unittest.main()
