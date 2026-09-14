"""OI-180—189 behavioral counterexamples; all data and publication writes isolated."""
import contextlib
import copy
import csv
import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import backtest_valuation_strategy as bt
import daily_execution_guard as guard
import screen_daily_volume_price_signals as s
import track_holdings_daily as tracker
from lot_cooldown import CooldownBook, EXECUTION_FIELDS

DAY = '2026-09-14'


def row(code='000651', price=100., pv=.5, **kw):
    return dict(security_code=code, security_name='synthetic', close=price, ma20=price*.95,
                ma60=price*.9, model_pv=pv, hold_pv=pv, signal_state='ok', trade_date=DAY, **kw)


def holding(shares=1000, cost=100):
    return dict(name='synthetic', shares=shares, cost=cost, stop=None)


def plan(rows, holdings=None, members=None, **kw):
    s.CLOSE_SERIES.clear()
    return s.section93_execution_plan(rows, 1e6, 100000., holdings or {}, set(), set(),
                                      members if members is not None else {r['security_code'] for r in rows}, **kw)


class PricesAndPlans(unittest.TestCase):
    def test_signal_day_tranche_not_execution_nav(self):
        days = ['2024-01-02', '2024-01-03', '2024-01-04']
        states = {d: [('A', p, 40., p/40)] for d,p in zip(days, [10.,10.,12.])}
        prices = {'A': {d: r[0][1] for d,r in states.items()}}
        ma = {'A': {d:{20:8.,60:7.} for d in days}}
        results = []
        for mode in ('legacy', 'signal'):
            ledger=[]
            with patch.object(bt,'trade_fee',return_value=0), patch.object(bt,'DELISTED_LAST',{}):
                bt.run('trend', .05, states, prices, {}, ma, days[0], days[-1], 1e6,
                       trend_tranche=True, trend_ma=(20,60), exec_delay=1,
                       lot_size=100, execution_consistency=mode, ledger=ledger)
            results.append([float(r['shares']) for r in ledger if r['action']=='买入'][-1])
        self.assertEqual(results, [4200,4100])

    def test_sell_opportunity_consumed_before_missing_next_day_quote(self):
        days=['2024-01-02','2024-01-03']
        states={days[0]:[('A',4500.,2000.,2.25)],days[1]:[]}
        counts=[]
        for mode in ('legacy','signal'):
            lot=bt.Lot('A','2023-01-02',.5,2000.,1800.,2200.,1.,shares=1000,avg_cost=1000.,invested=1e6)
            portfolio=bt.Portfolio(cash=1e6,lots={'A':lot})
            original=bt.Opportunities
            seen=[]
            def opportunities(counters):
                seen.append(counters)
                if len(seen)==2:
                    counters['A']=2
                return original(counters)
            with patch.object(bt,'Portfolio',return_value=portfolio), patch.object(bt,'Opportunities',side_effect=opportunities):
                bt.run('trend',.05,states,{'A':{days[0]:4500.}}, {}, {'A':{days[0]:{20:4000.,60:3000.}}},
                       days[0],days[-1],5.5e6,trend_tranche=True,trend_ma=(20,60),exec_delay=1,
                       gain_sell=1.1,gain_sell_mode='ungated',lot_size=100,lot_ratio_cooldown=True,
                       execution_consistency=mode)
            counts.append(seen[1]['A'])
        self.assertEqual(counts,[2,1])

    def test_no_zero_share_swap(self):
        day='2024-01-03'
        states={day:[('A',100.,50.,2.),('B',1.,2.,.5)]}
        ma={'A':{day:{20:110.,60:80.}},'B':{day:{20:.9,60:.8}}}
        lot=bt.Lot('A','2024-01-02',2.,50.,40.,60.,-.5,shares=50,avg_cost=100.,invested=5000.)
        ledger=[]
        with patch.object(bt,'Portfolio',return_value=bt.Portfolio(cash=1.,lots={'A':lot})):
            result=bt.run('trend',.05,states,{'A':{day:100.},'B':{day:1.}}, {}, ma,day,day,5001.,
                          trend_tranche=True,trend_ma=(20,60),swap=True,swap_partial=True,
                          swap_require_weak=True,lot_size=100,lot_ratio_cooldown=True,
                          exec_delay=0,ledger=ledger)
        self.assertFalse([r for r in ledger if r['action']=='卖出'])
        self.assertEqual(result['stats'].get('换仓·减一档',0),0)

    def test_nonmember_cannot_buy_or_trigger_swap(self):
        result=plan([row()], {'000338':holding()}, members=set(), holding_rows=[row('000338',pv=2.)])
        self.assertFalse(result['plan'])
        self.assertFalse([r for r in result['sells'] if r['rule']=='换仓'])

    def test_exit_cannot_rebuy_or_be_swap_source_twice(self):
        result=plan([row(),row('000338')], {'000651':holding(100000,20)}, members={'000338'})
        self.assertNotIn('000651',[r['security_code'] for r in result['plan']])
        self.assertEqual(len([r for r in result['sells'] if r['security_code']=='000651']),1)

    def test_missing_mark_blocks_new_buy(self):
        result=plan([row()],{'000338':holding(10000)},exposure_cap=.3,cap_cash=500000)
        self.assertFalse(result['valuation_complete'])
        self.assertIsNone(result['eb_stock_before'])
        self.assertIsNone(result['eb_stock_after'])
        self.assertFalse(result['plan'])
        result['eb']=dict(spread=.02,observed_on=DAY,cap=.3,cash=500000,debt=0,source='test')
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            s.report_section93(result,1e6,Path(tmp)/'buy.csv',DAY)
        self.assertIn('标价缺失',out.getvalue())

    def test_suspended_holding_counts_toward_cap_but_cannot_trade(self):
        suspended=dict(security_code='000338',close=None,mark_close=100.,mark_date='2026-09-11',tradable=False)
        result=plan([row()],{'000338':holding(10000)},holding_rows=[suspended],exposure_cap=.3,cap_cash=500000)
        self.assertTrue(result['valuation_complete'])
        self.assertEqual(result['eb_stock_before'],1e6)
        self.assertFalse(result['plan'])
        self.assertFalse([r for r in result['sells'] if r['sell_shares']])

    def test_stale_bar_never_tradable(self):
        candles=[dict(date=(date(2026,6,1)+timedelta(days=i)).isoformat(),open=100+i,
                      close=100+i,volume=1000,amount=100000) for i in range(80)]
        with patch.object(s,'fetch_daily_rows',return_value=('fake',candles)):
            snapshot=s.scan_one({'security_code':'000651','close':9999,'signal_state':'ok'},DAY,1)
        self.assertIsNone(snapshot['close'])
        self.assertFalse(snapshot['tradable'])
        self.assertEqual(snapshot['signal_state'],'no_session_quote')
        snapshot['model_pv']=.5
        self.assertFalse(plan([snapshot])['plan'])

    def test_zero_volume_placeholder_is_not_a_session_quote(self):
        raw=[dict(date='2026-09-11',close=100.,volume=1000),dict(date=DAY,close=100.,volume=0)]
        rows=s.rebase_price_rows(raw,'A',DAY,{})
        self.assertEqual([r['date'] for r in rows],['2026-09-11'])

    def test_rebase_uses_all_events_no_future_or_fabricated_bar(self):
        raw=[dict(date='2024-01-01',close=30.,open=30.,volume=100),dict(date='2024-01-06',close=10.,open=10.,volume=340)]
        events={'2024-01-02':(2.,1.,0.,0.),'2024-01-04':(3.,.5,.2,4.),'2024-02-01':(50.,0.,0.,0.)}
        r=s.rebase_price_rows(raw,'A','2024-01-07',events)
        self.assertEqual(len(r),2)
        self.assertAlmostEqual(r[0]['close'],((30-2)/2-3+.2*4)/1.7)
        self.assertEqual(r[-1]['close'],10.)
        self.assertEqual(r[0]['raw_close'],30.)
        self.assertEqual(s.rebase_price_rows(raw,'A','2024-01-03',events)[0]['close'],14.)

    def test_scanner_tracker_same_raw_basis(self):
        rows=[dict(date=(date(2026,7,17)+timedelta(days=i)).isoformat(),close=100.,open=100.,
                   volume=100,amount=10000) for i in range(60)]
        rows=s.rebase_price_rows(rows,'A',DAY,{DAY:(2,1,0,0)})
        rows[-1].update(close=49.,raw_close=49.)
        with patch.object(s,'fetch_daily_rows',return_value=('fake',copy.deepcopy(rows))), \
             patch.object(tracker,'fetch_daily_rows',return_value=('fake',copy.deepcopy(rows))):
            sr=s.scan_one(dict(security_code='000651'),DAY,1)
            tr=tracker.fetch_raw_close('000651',date.fromisoformat(DAY),1)
        self.assertEqual((sr['close'],sr['ma20'],sr['ma60']),tuple(round(x,4) for x in tr))

    def test_raw_history_not_tencent_adjusted_tail(self):
        from unittest.mock import MagicMock
        payload={'data':{'sz000651':{'qfqday':[['2026-09-11','100','100','100','100','10']]}}}
        response=MagicMock();response.__enter__.return_value.read.return_value=json.dumps(payload).encode()
        with patch.object(s.urllib.request,'urlopen',return_value=response) as fetch:
            _,rows=s.fetch_daily_rows_tencent('000651','SZSE',DAY,1,'qfq')
        self.assertEqual(len(rows),1)
        self.assertEqual(fetch.call_count,1)

    def test_hold_pv_does_not_fall_back(self):
        self.assertIsNone(s.hold_pv_of({'model_pv':.5,'hold_pv':''}))


class GuardedExecution(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.p=Path(self.tmp.name)
        self.a=SimpleNamespace(as_of=DAY, input=self.p/'pool.csv',review_queue=self.p/'queue.csv',tiers=self.p/'tiers.csv',
            holdings=self.p/'holdings.csv',triage=self.p/'triage.csv',model_bands=self.p/'bands.csv',hold_bands=self.p/'holdbands.csv',
            evidence_proof=self.p/'evidence.json',nav=1e6,funds=100000.,cash=100000.,debt=0.,symbols='',rf=.02,
            cooldown_state=self.p/'cooldown.csv',cooldown_executions=self.p/'executions.csv',since='',timeout=1,workers=1,
            publication=self.p/'publication.json',output_csv=self.p/'quotes.csv',plan_out=self.p/'buys.csv',
            sell_out=self.p/'sells.csv',tracking_out=self.p/'tracked.csv',log_file=self.p/'log.csv')
        self.write(self.a.input,[dict(security_code='000651',security_name='synthetic',fair_price_low=180,fair_price_high=220)])
        self.write(self.a.tiers,[dict(security_code='000651',quality_tier='L2',tactical_thesis='')])
        self.write(self.a.triage,[dict(security_code='000651',attention_class='worth_attention')])
        self.write(self.a.holdings,[],['security_code','current_shares','cost_basis','entry_stop_price'])
        self.write(self.a.review_queue,[],['security_code','buy_blocked','as_of'])
        for path in (self.a.model_bands,self.a.hold_bands):
            self.write(path,[dict(security_code='000651',intrinsic_value=200,available_at='2026-08-31',status='ok',band_low=180,band_high=220)])
        self.write(self.a.cooldown_executions,[],EXECUTION_FIELDS)
        guard.stamp(self.a.review_queue,DAY)
        guard.atomic_json(self.a.evidence_proof,dict(status='complete',as_of=DAY,since='2026-09-13',covered_codes=['000651'],inputs={}))
        self.quote=row(mark_close=100.,mark_date=DAY,tradable=True)
        self.addCleanup(patch.stopall)
        patch.object(bt,'load_actions',return_value={}).start()
        patch.object(s,'equity_bond_signal',return_value=(None,None)).start()
        patch.object(s,'parse_args',return_value=self.a).start()
        patch.object(s,'scan',return_value=[copy.deepcopy(self.quote)]).start()
        import check_report_day_price_divergence as events
        self.events=patch.object(events,'run',return_value=[]).start()
        self.out=contextlib.redirect_stdout(io.StringIO());self.out.__enter__();self.addCleanup(self.out.__exit__,None,None,None)
        self.err=contextlib.redirect_stderr(io.StringIO());self.err.__enter__();self.addCleanup(self.err.__exit__,None,None,None)

    @staticmethod
    def write(path,rows,fields=None):
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields or list(rows[0]));w.writeheader();w.writerows(rows)

    def test_empty_holdings_and_queue_valid_with_receipt(self):
        self.assertEqual(s.main(),0)
        value=guard.verify_publication(self.a.publication,DAY)
        self.assertEqual(value['status'],'complete')
        with self.a.plan_out.open() as f:self.assertEqual(len(list(csv.DictReader(f))),1)

    def test_each_required_file_missing(self):
        for name in ('input','review_queue','tiers','holdings','triage','model_bands','hold_bands','evidence_proof'):
            with self.subTest(name=name):
                path=getattr(self.a,name);content=path.read_bytes();path.unlink()
                try:self.assertEqual(s.main(),1)
                finally:path.write_bytes(content)
                self.assertFalse(self.a.plan_out.exists())
                self.assertFalse(self.a.cooldown_state.exists())

    def test_queue_freshness_and_hash_even_empty(self):
        guard.stamp(self.a.review_queue,'2026-09-11')
        self.assertEqual(s.main(),1)
        guard.stamp(self.a.review_queue,DAY)
        self.a.review_queue.write_text(self.a.review_queue.read_text()+'\n')
        self.assertEqual(s.main(),1)

    def test_cross_stage_evidence_change(self):
        source=self.p/'source';source.write_text('old')
        guard.atomic_json(self.a.evidence_proof,dict(status='complete',as_of=DAY,since='2026-09-13',
            covered_codes=['000651'],inputs={str(source):guard.digest(source)}))
        source.write_text('new')
        self.assertEqual(s.main(),1)

    def test_new_code_requires_evidence_coverage(self):
        data=json.loads(self.a.evidence_proof.read_text());data['covered_codes']=[]
        guard.atomic_json(self.a.evidence_proof,data)
        self.assertEqual(s.main(),1)

    def test_pending_corporate_action_blocks_before_scan(self):
        self.write(self.a.holdings,[dict(security_code='000651',current_shares=100,cost_basis=100,entry_stop_price=80)])
        with patch.object(bt,'load_actions',return_value={'000651':{DAY:(1,1,0,0)}}):
            self.assertEqual(s.main(),1)
        s.scan.assert_not_called()

    def test_event_failure_leaves_old_files_but_invalidates_permission(self):
        self.assertEqual(s.main(),0)
        before={p:p.read_bytes() for p in (self.a.plan_out,self.a.cooldown_state,self.a.log_file)}
        self.events.side_effect=ValueError('injected event failure')
        self.assertEqual(s.main(),1)
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)
        with self.assertRaises(ValueError):guard.verify_publication(self.a.publication,DAY)

    def test_quote_failure_no_outputs(self):
        s.scan.return_value=[dict(self.quote,signal_state='data_error')]
        self.assertEqual(s.main(),1)
        self.assertFalse(self.a.cooldown_state.exists())
        self.assertFalse(self.a.plan_out.exists())

    def test_postwrite_failure_rolls_back_cooldown_and_all_outputs(self):
        self.assertEqual(s.main(),0)
        before={p:p.read_bytes() for p in (self.a.output_csv,self.a.plan_out,self.a.cooldown_state,self.a.log_file)}
        original=CooldownBook.save
        def fail(book,counters):
            original(book,counters)
            book.path.write_text('injected partial state write')
            raise ValueError('injected after state write')
        with patch.object(CooldownBook,'save',fail):self.assertEqual(s.main(),1)
        for p,b in before.items():self.assertEqual(p.read_bytes(),b)
        self.assertEqual(json.loads(self.a.publication.read_text())['status'],'failed')

    def test_missing_secondary_holding_quote_no_publication(self):
        self.write(self.a.holdings,[dict(security_code='000338',current_shares=100,cost_basis=100,entry_stop_price=80)])
        evidence=json.loads(self.a.evidence_proof.read_text());evidence['covered_codes'].append('000338')
        guard.atomic_json(self.a.evidence_proof,evidence)
        s.scan.side_effect=[[copy.deepcopy(self.quote)],[dict(security_code='000338',signal_state='data_error')]]
        self.assertEqual(s.main(),1)
        self.assertFalse(self.a.cooldown_state.exists())

    def test_old_account_snapshot_rejected(self):
        self.a.cash=None;self.a.debt=None
        with patch.object(s,'latest_account_snapshot',return_value=dict(as_of='2026-09-11',cash_cny='1000',margin_debt_cny='0')):
            self.assertEqual(s.main(),1)

    def test_missing_or_rejected_model_stays_empty_even_with_old_pool_band(self):
        self.write(self.a.holdings,[dict(security_code='000651',current_shares=100,cost_basis=100,entry_stop_price=80)])
        for band in ({},{'000651':dict(status='rejected',intrinsic_value=200)}):
            with self.subTest(band=band):
                rows=tracker.track(self.a.holdings,self.a.input,date.fromisoformat(DAY),'',1,
                    snapshots={'000651':self.quote},hold_bands=band,candidate_bands=band,members={'000651'})
                self.assertEqual(rows[0]['pv'],'')
                self.assertEqual(rows[0]['action'],'数据缺失')
                self.assertNotIn('逐日清仓',rows[0]['note'])

    def test_no_pool_row_does_not_mean_no_membership(self):
        self.write(self.a.holdings,[dict(security_code='000338',current_shares=100,cost_basis=100,entry_stop_price=80)])
        rows=tracker.track(self.a.holdings,self.a.input,date.fromisoformat(DAY),'',1,
            snapshots={'000338':self.quote},hold_bands={},candidate_bands={},members={'000338'})
        self.assertNotIn('逐日清仓',rows[0]['note'])

    def test_publication_detects_later_output_or_input_change(self):
        self.assertEqual(s.main(),0)
        self.a.holdings.write_text('changed')
        with self.assertRaises(ValueError):guard.verify_publication(self.a.publication,DAY)


class PublicationRecovery(unittest.TestCase):
    def test_concurrent_change_is_not_overwritten_by_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'output';path.write_text('old');status=Path(tmp)/'status.json'
            with self.assertRaises(ValueError):
                with guard.Publication(status,DAY,[path]) as tx:
                    stage=tx.stage(path);stage.write_text('this run')
                    path.write_text('other writer')
                    tx.publish({path:stage},{})
            self.assertEqual(path.read_text(),'other writer')

    def test_interrupted_install_restored_before_state_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);state=p/'state';state.write_text('half installed');backup=p/'backup';backup.write_text('original')
            status=p/'status.json'
            guard.atomic_json(status,dict(status='running',phase='installing',as_of=DAY,backups={str(state):str(backup)}))
            with guard.Publication(status,DAY,[state]):
                self.assertEqual(state.read_text(),'original')
            self.assertEqual(state.read_text(),'original')

    def test_final_event_check_uses_newly_eligible_rows_and_fails_on_provider_error(self):
        import check_report_day_price_divergence as e
        with patch.object(e,'load_csv',side_effect=[[dict(security_code='000651',fair_price_low='180',fair_price_high='220')],[]]), \
             patch.object(e,'latest_notice_dates',return_value={'000651':('2026-09-11','periodic_report')}), \
             patch.object(e,'divergence_for',side_effect=ValueError('unavailable')) as check:
            with self.assertRaises(ValueError):
                e.run(date.fromisoformat(DAY),10,1,candidate_rows=[row()],members={'000651'},tactical=set(),strict=True)
            self.assertEqual(check.call_args.args[0],'000651')

    def test_newer_rejection_prevents_older_model_revival(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bands.csv'
            fields=['security_code','status','available_at','intrinsic_value']
            GuardedExecution.write(path,[dict(zip(fields,['000651','ok','2026-08-01','200'])),
                                        dict(zip(fields,['000651','rejected','2026-09-01','300']))])
            self.assertEqual(s.load_model_bands(path,DAY),{})



if __name__=='__main__':
    unittest.main()
