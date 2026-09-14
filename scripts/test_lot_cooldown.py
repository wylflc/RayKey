"""OI-186: confirmed receipts, opportunity consumption and replay boundaries."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import lot_cooldown as cd
import test_daily_execution_plan as plan
from test_daily_execution_plan import row, hold
from test_position_cap_lot import path as backtest_path


class ReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state.csv'
        self.receipts = self.state.with_name('cooldown_executions.csv')
        self.fill = dict(execution_id='local-1', signal_date='2026-09-10', execution_date='2026-09-11',
                         security_code='000001', security_name='A', side='buy', rule='buy',
                         shares=100, price=4500, tranche=150000)

    def record(self, **changes):
        return cd.record_execution(dict(self.fill, **changes), self.receipts, self.state)

    def load(self, day='2026-09-11'):
        return cd.CooldownBook.load(self.state, day, self.receipts)

    def consume(self, day):
        book = self.load(day)
        after = deepcopy(book.before)
        opportunity = cd.Opportunities(after['buy'])
        ready = opportunity.ready('000001')
        self.assertEqual(opportunity.ready('000001'), ready)
        book.save(after)
        return ready, after['buy'].get('000001', 0)

    def test_scan_cannot_invent_confirmation(self):
        book = self.load()
        with self.assertRaises(ValueError):
            book.save({'buy': {'000001': 2}, 'sell': {}})
        book.save(book.before)
        self.assertFalse(self.receipts.exists())

    def test_confirmation_and_same_day_replay(self):
        self.assertTrue(self.record())
        self.assertEqual(self.consume('2026-09-11'), (False, 1))
        self.assertEqual(self.consume('2026-09-11'), (False, 1))
        self.assertEqual(self.consume('2026-09-14'), (False, 0))
        self.assertEqual(self.consume('2026-09-15'), (True, 0))
        self.assertEqual(self.consume('2026-09-16'), (True, 0))

    def test_no_signal_does_not_consume(self):
        self.record()
        book = self.load()
        book.save(book.before)
        self.assertEqual(self.load('2026-09-14').before['buy']['000001'], 2)

    def test_duplicate_receipt_is_idempotent_and_conflict_fails(self):
        self.record()
        self.assertFalse(self.record())
        with self.assertRaises(ValueError):
            self.record(price=4501)
        self.assertEqual(len(cd.read_rows(self.receipts)), 1)

    def test_partial_fills_are_aggregated_and_late_same_day_rescanned(self):
        self.record(shares=40)
        self.assertEqual(self.consume('2026-09-11'), (True, 0))
        self.record(execution_id='local-2', shares=60)
        self.assertEqual(self.consume('2026-09-11'), (False, 1))
        self.assertEqual(self.consume('2026-09-11'), (False, 1))

    def test_new_execution_after_expiry_restarts_from_actual_amount(self):
        self.record()
        for day in ['2026-09-11', '2026-09-14', '2026-09-15']:
            self.consume(day)
        self.record(execution_id='local-2', signal_date='2026-09-15', execution_date='2026-09-16', price=6000)
        self.assertEqual(self.consume('2026-09-16'), (False, 2))

    def test_history_is_readonly(self):
        self.record()
        self.consume('2026-09-14')
        book = self.load('2026-09-10')
        self.assertFalse(book.writable)
        self.assertEqual(book.before, {'buy': {}, 'sell': {}})
        with self.assertRaises(ValueError):
            book.save(book.before)

    def test_backdated_receipt_rejected_even_without_existing_counters(self):
        book = self.load('2026-09-14')
        book.save(book.before)
        with self.assertRaises(ValueError):
            self.record()
        self.assertFalse(self.receipts.exists())

    def test_changed_receipt_during_scan_requires_retry(self):
        book = self.load()
        self.record()
        with self.assertRaises(ValueError):
            book.save(book.before)

    def test_legacy_unconfirmed_active_state_rejected(self):
        cd.atomic_csv(self.state, [dict(security_code='000001', side='buy', remaining_skips=2,
                      remaining_before=2, applied_trade_date='2026-09-10')], cd.STATE_FIELDS)
        with self.assertRaises(ValueError):
            self.load()

    def test_buy_sell_are_independent(self):
        self.record()
        self.record(execution_id='local-sell', side='sell', rule='gain', price=6000)
        self.assertEqual(self.load().before, {'buy': {'000001': 2}, 'sell': {'000001': 3}})

    def test_bad_receipts_rejected(self):
        for changes in [dict(security_code=''), dict(shares=0), dict(price=float('nan')),
                        dict(tranche=-1), dict(execution_date='2026-09-10'), dict(rule='stop')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.record(**changes)
        self.record(shares=40)
        with self.assertRaises(ValueError):
            self.record(execution_id='different-tranche', shares=60, tranche=160000)

    def test_ordinary_lot_residual_clear_does_not_start_high_price_cooldown(self):
        self.record(side='sell', rule='gain', shares=200, price=1400)
        self.assertEqual(self.load().before['sell']['000001'], 0)

    def test_cli_logs_confirmation_once_and_can_repair_missing_log(self):
        import contextlib
        import io
        from unittest.mock import patch
        import record_cooldown_execution as cli
        log = self.state.with_name('decision.csv')
        argv = ['record_cooldown_execution', '--execution-id', 'local-1', '--signal-date', '2026-09-10',
                '--as-of', '2026-09-11', '--code', '000001', '--name', 'A', '--side', 'buy', '--rule', 'buy',
                '--shares', '100', '--price', '4500', '--tranche', '150000',
                '--executions', str(self.receipts), '--state', str(self.state), '--log-file', str(log)]
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
            self.assertEqual(cli.main(), 0)
            self.assertEqual(len(cd.read_rows(log)), 1)
            log.unlink()  # 回执已写、日志未完成的重试
            self.assertEqual(cli.main(), 0)
        self.assertEqual(len(cd.read_rows(self.receipts)), 1)
        self.assertEqual(len(cd.read_rows(log)), 1)
        self.assertEqual(cd.read_rows(log)[0]['input_files'], str(self.receipts))

    def test_failed_scan_does_not_publish_or_advance_state(self):
        import contextlib
        import io
        from types import SimpleNamespace
        from unittest.mock import patch
        import screen_daily_volume_price_signals as scan
        self.record()
        book = self.load(); book.save(book.before)
        before = self.state.read_bytes()
        output = self.state.with_name('buy_candidates.csv'); output.write_text('previous scan')
        args = SimpleNamespace(as_of='2026-09-14', rf=.02, symbols='', input=output,
                               output_csv=output, since='', timeout=1, workers=1)
        with patch.object(scan, 'parse_args', return_value=args), patch.object(scan, 'load_csv', return_value=[]), \
             patch.object(scan, 'scan', return_value=[{'signal_state':'data_error'}, {'signal_state':'buy_candidate'}]), \
             patch.object(scan, 'report_section93') as publish, contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(scan.main(), 0)
        publish.assert_not_called()
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(output.read_text(), 'previous scan')


class OpportunityPlanTest(unittest.TestCase):
    setUp = plan.ExecutionPlanTest.setUp
    run_plan = plan.ExecutionPlanTest.run_plan

    def test_unexecuted_plan_and_no_cash_never_start(self):
        r = row('000021', 'Q', 4500, 4000, 3500, .5)
        counters = {}
        self.assertFalse(self.run_plan([r], {}, 1000, counters=counters)['plan'])
        self.assertEqual(counters, {})
        self.assertEqual(len(self.run_plan([r], {}, 1e6, counters=counters)['plan']), 1)
        self.assertEqual(len(self.run_plan([r], {}, 1e6, counters=counters)['plan']), 1)
        self.assertEqual(counters, {})

    def test_active_counter_consumed_when_price_fits_or_cash_empty(self):
        r = row('000021', 'Q', 100, 90, 80, .5)
        counters = {'000021': 2}
        self.assertFalse(self.run_plan([r], {}, 0, counters=counters)['plan'])
        self.assertEqual(counters['000021'], 1)
        self.assertFalse(self.run_plan([r], {}, 1e6, counters=counters)['plan'])
        self.assertEqual(counters['000021'], 0)

    def test_ineligible_day_does_not_consume(self):
        r = row('000021', 'Q', 4500, 4600, 4700, .5)
        counters = {'000021': 2}
        self.run_plan([r], {}, 1e6, counters=counters)
        self.assertEqual(counters['000021'], 2)

    def test_sell_counter_applies_after_price_falls_below_tranche(self):
        r = row('000021', 'Q', 100, 110, 80, 3.)
        counters = {'000021': 2}
        result = self.run_plan([r], {'000021': hold('Q', 5000, 30, None)}, 0, sell_counters=counters)
        self.assertFalse(result['sells'])
        self.assertEqual(counters['000021'], 1)


class EngineTest(unittest.TestCase):
    def test_confirmed_buy_skips_subsequent_two_qualified_signals(self):
        ledger, result = backtest_path([4500] * 8, 3e6, position_cap=0.)
        buys = [r for r in ledger if r['action'] == '买入']
        self.assertEqual([r['date'] for r in buys], ['2024-01-03', '2024-01-06', '2024-01-09'])
        self.assertEqual(result['stats']['确认净成交·冷却启动'], 3)

    def test_unaffordable_order_does_not_start(self):
        ledger, result = backtest_path([45000] * 4 + [4500] * 2, 3e6, position_cap=0.)
        self.assertEqual([r['date'] for r in ledger if r['action'] == '买入'], ['2024-01-06'])
        self.assertEqual(result['stats']['确认净成交·冷却启动'], 1)

    def test_existing_counter_applies_when_lot_fits(self):
        ledger, _ = backtest_path([4500, 4500, 100, 100, 100], 3e6, position_cap=0.)
        self.assertEqual([r['date'] for r in ledger if r['action'] == '买入'], ['2024-01-03', '2024-01-06'])

    def test_cooldown_denominator_uses_original_signal_nav(self):
        from unittest.mock import patch
        with patch('backtest_valuation_strategy.cooldown_skips', wraps=cd.cooldown_skips) as formula:
            _, result = backtest_path([1000, 1000, 4500], 3e6, position_cap=0.)
        self.assertEqual(len(formula.call_args_list), 1)
        amount, tranche = formula.call_args.args
        self.assertEqual(amount, 450000)
        self.assertAlmostEqual(tranche, result['equity'][1][1] * .05)
        self.assertNotAlmostEqual(tranche, result['equity'][2][1] * .05)

    def test_net_zero_sale_and_buy_do_not_activate(self):
        import backtest_valuation_strategy as bt
        days = ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08']
        prices = [1000, 1000, 4500, 4500, 4500]
        ratios = [.5, 3., .5, .5, .5]
        states = {d: [('A', p, p/r, r)] for d,p,r in zip(days, prices, ratios)}
        mas = {'A': {d: {20: p*.9, 60: p*.8} for d,p in zip(days, prices)}}
        ledger = []
        result = bt.run('trend', .05, states, {'A': dict(zip(days, prices))}, {}, mas,
                        days[0], days[-1], 3e6, trend_tranche=True, trend_ma=(20,60),
                        exec_delay=1, lot_size=100, lot_ratio_cooldown=True,
                        gain_sell=1.1, gain_sell_mode='ungated', net_same_day=True, ledger=ledger)
        self.assertGreater(result['stats']['同日买卖对冲'], 0)
        self.assertEqual(result['stats'].get('确认净成交·冷却启动', 0), 0)
        self.assertEqual(sum(float(r['shares']) for r in ledger if r['action'] == '卖出'), 0)

    def test_odd_lot_swap_path_is_unchanged_by_cooldown_start_mode(self):
        from unittest.mock import patch
        import backtest_valuation_strategy as bt
        day = '2024-01-03'
        states = {day:[('A',100.,50.,2.), ('B',1.,2.,.5)]}
        prices = {'A':{day:100.}, 'B':{day:1.}}
        mas = {'A':{day:{20:110.,60:80.}}, 'B':{day:{20:.9,60:.8}}}
        paths = []
        for mode in ('plan', 'confirmed'):
            lot = bt.Lot(code='A', entry_date='2024-01-02', entry_ratio=2., entry_value=50.,
                         entry_band_low=40., entry_band_high=60., entry_upside=-.5,
                         shares=50, avg_cost=100., invested=5000.)
            portfolio = bt.Portfolio(cash=1., lots={'A':lot})
            ledger = []
            with patch.object(bt, 'Portfolio', return_value=portfolio):
                result = bt.run('trend', .05, states, prices, {}, mas, day, day, 5001.,
                                trend_tranche=True, trend_ma=(20,60), swap=True, swap_partial=True,
                                swap_require_weak=True, lot_size=100, lot_ratio_cooldown=True,
                                lot_cooldown_start=mode, exec_delay=0, ledger=ledger)
            paths.append((result['equity'], ledger))
        self.assertEqual(paths[0], paths[1])


if __name__ == '__main__':
    unittest.main()
