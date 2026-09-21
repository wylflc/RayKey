"""OI-197: independently check cash entitlements and exchange price mechanics."""
import csv,json,pickle,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import corporate_actions as ca
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bands
import screen_daily_volume_price_signals as live
import apply_holdings_corporate_action as holdings
from test_corporate_actions_tax import make_lot
from test_apply_holdings_corporate_action import write_holdings

class PriceTermsTest(unittest.TestCase):
    def setUp(self):
        self.event=ca.CorporateAction((.45,.3,0.,0.),(.44957,.29971,0.,0.))
        self.day='2025-06-16'

    def test_cash_tax_and_shares_actual_stops_exchange(self):
        pf=bt.Portfolio(cash=0.);pf.lots['X']=make_lot('X',1000.,'2025-01-01',100.,90.)
        lot=pf.lots['X'];lot.trail_peak=110.;lot.lock_level=95.;lot.peak_price=120.
        with patch.object(bt,'WITHHOLDING',0):
            credited=bt.apply_corporate_actions(pf,self.day,{'X':{self.day:self.event}})
        self.assertEqual(credited,450.);self.assertEqual(lot.shares,1300.)
        self.assertEqual(lot.sublots[0][2],450.);self.assertEqual(lot.sublots[0][1],1300.)
        for field,old in [('entry_stop',90),('avg_cost',100),('trail_peak',110),('lock_level',95),('peak_price',120)]:
            self.assertAlmostEqual(getattr(lot,field),(old-.44957)/1.29971)
        with patch.object(bt,'DIVIDEND_TAX_ON',True):
            self.assertAlmostEqual(bt.sell_dividend_tax(pf,lot,1300.,'2025-06-17'),45.)

    def test_price_rebase_but_total_return_uses_actual(self):
        events={self.day:self.event};prices={'2025-06-13':100.,self.day:77.}
        self.assertAlmostEqual(bt.adjusted_close_series(prices,events)['2025-06-13'],(100-.44957)/1.29971)
        self.assertAlmostEqual(bt.daily_returns({'X':prices},{'X':events})['X'][self.day],(77*1.3+.45)/100-1)
        self.assertEqual(list(bt.quote_action_factors(sorted(prices),events))[-1],(1.3,.45))

    def test_missing_quote_and_future_event_boundary(self):
        raw=[dict(date='2025-06-13',close=100.,volume=1000.)]
        before=live.rebase_price_rows(raw,'X','2025-06-15',events={self.day:self.event})
        after=live.rebase_price_rows(raw,'X','2025-06-17',events={self.day:self.event})
        self.assertEqual(before[0]['close'],100.)
        self.assertAlmostEqual(after[0]['close'],(100-.44957)/1.29971)
        self.assertAlmostEqual(after[0]['volume'],1300.)
        self.assertEqual(len(after),1)

    def test_pickle_and_snapshot_keep_both_bases(self):
        got=pickle.loads(pickle.dumps(self.event));self.assertEqual(tuple(got),tuple(self.event));self.assertEqual(got.price,self.event.price)
        row=dict(zip(ca.AMOUNTS,self.event))|dict(zip(ca.PRICE_FIELDS,self.event.price))
        self.assertEqual(ca.event_from_row(json.loads(json.dumps(row))).price,self.event.price)
        with self.assertRaises(ValueError):ca.event_from_row(dict(cash_per_share=.45,price_cash_per_share=.44957))

    def test_same_day_two_fiscal_plans_single_price_override(self):
        rows=[dict(security_code='002043',ex_dividend_date='2026-06-01',cash_per_share=cash,share_ratio='0',report_date=report)
              for cash,report in [('.132','2025-12-31'),('.180','2026-03-31')]]
        event=ca.event_map(rows*2)['002043']['2026-06-01']
        self.assertEqual(event[0],.312);self.assertEqual(event.price[0],.3080016)
        value,_,_=bands.exright_adjust(rows,'2026-01-01','2026-06-01',(20,))
        self.assertAlmostEqual(value[0],20-.3080016)
        self.assertEqual(sum(float(r['cash_per_share']) for r in rows),.312)
        with self.assertRaisesRegex(ValueError,'Actual distribution changed'):
            ca.event_map([dict(rows[0],cash_per_share='.313')])

    def test_actual_split_for_bookkeeping_price_split_for_band(self):
        row=dict(security_code='688019',ex_dividend_date=self.day,cash_per_share='.45',share_ratio='.3')
        self.assertEqual(bands.split_factor([row],'2025-01-01',self.day),1.3)
        value,_,_=bands.exright_adjust([row],'2025-01-01',self.day,(100.,))
        self.assertAlmostEqual(value[0],(100-.44957)/1.29971)

    def test_duplicate_and_late_evidence_rejected(self):
        row=ca.price_overrides()['002043','2026-06-01']
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'terms.csv'
            for rows in ([row,row],[dict(row,notice_date='2026-06-02')]):
                with path.open('w',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=row);w.writeheader();w.writerows(rows)
                with patch.object(ca,'PRICE_TERMS_PATH',path),self.assertRaises(ValueError):ca.price_overrides()

    def test_holdings_actual_shares_and_both_ledger_bases(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td)/'h.csv';ledger=Path(td)/'ledger.csv';write_holdings(h)
            result=holdings.apply_action(h,ledger,None,'600036',self.day,.45,.3,.1,10.,True,'test',price=(.44957,.29971,.1,10.))
            self.assertEqual(result['shares_after'],'1400')
            self.assertEqual(result['cash_per_share'],'0.45')
            self.assertEqual(result['price_cash_per_share'],'0.44957')
            self.assertAlmostEqual(float(result['stop_after']),(28-.44957+1)/1.39971,places=4)

    def test_header_only_legacy_ledger_is_migrated(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td)/'h.csv';ledger=Path(td)/'ledger.csv';write_holdings(h)
            legacy_fields=[k for k in holdings.LEDGER_FIELDS if k not in (*ca.PRICE_FIELDS,'amount_basis')]
            with ledger.open('w',newline='') as f:csv.writer(f).writerow(legacy_fields)
            holdings.apply_action(h,ledger,None,'600036',self.day,.45,0.,0.,0.,True,'test')
            with ledger.open() as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),1)
            self.assertNotIn(None,rows[0])
            self.assertEqual(rows[0]['amount_basis'],'actual_and_exchange')
            self.assertEqual(rows[0]['price_cash_per_share'],'0.45')

    def test_unequal_shareholder_cash_does_not_overstate_company_equity_bridge(self):
        with ca.COMPONENT_CORRECTIONS.open() as f:
            rule = next(r for r in csv.DictReader(f) if r['security_code']=='600989' and r['ex_dividend_date']=='2026-04-28')
        row={k:rule[k] for k in ca.ACTION_FIELDS}
        self.assertEqual(float(row['cash_per_share']),.4921)
        self.assertAlmostEqual(float(ca.accounting_cash(row))*7333360000,3054557999.96,places=4)
        actual=ca.event_map([row])['600989']['2026-04-28']
        self.assertEqual(actual[0],.4921)
        total=bands.dividends_total([row],'2026-01-01','2026-05-01',7333360000,'2025-12-31')
        self.assertAlmostEqual(total,3054557999.96,places=4)
        with ca.COMPONENT_CORRECTIONS.open() as f:
            older=[r for r in csv.DictReader(f) if r['security_code']=='600989' and r['ex_dividend_date']<'2021']
        self.assertEqual(len(older),2)
        for older_rule in older:
            self.assertEqual(older_rule['cash_per_share'],older_rule['expected_cash_per_share'])
            self.assertAlmostEqual(float(ca.accounting_cash(older_rule))*7333360000,2053312557.60,places=4)

    def test_source_component_correction_is_idempotent_and_guarded(self):
        with ca.COMPONENT_CORRECTIONS.open() as f:
            rule=next(r for r in csv.DictReader(f) if r['security_code']=='300750')
        row={k:rule[k] for k in ca.ACTION_FIELDS};old=dict(row,cash_per_share='2.011')
        self.assertEqual(ca.correct_components([old]),ca.correct_components([row]))
        self.assertEqual(ca.correct_components([old])[0]['cash_per_share'],'5.028')
        with self.assertRaisesRegex(ValueError,'Corrected source component changed'):
            ca.correct_components([dict(old,cash_per_share='2.5')])

    def test_reverse_split_compatibility(self):
        event=ca.event_from_row(dict(cash_per_share=0,share_ratio=-.9))
        self.assertAlmostEqual(bt.adjusted_close_series({'2020-01-01':1.,'2020-01-03':10.},{'2020-01-02':event})['2020-01-01'],10.)

    def test_shadow_correction_waits_for_ex_date_and_preserves_archive(self):
        from shadow_from_origin import corrected_actions
        snapshots=[dict(date=day,all_actions={'X':{}},actions={})
                   for day in ['2025-06-13','2025-06-16','2025-06-17']]
        original=json.dumps(snapshots,sort_keys=True)
        event=dict(zip(ca.AMOUNTS,self.event))|dict(zip(ca.PRICE_FIELDS,self.event.price))
        correction=dict(availability='per_event',through='2025-06-16',
                        events={'X':{self.day:event}},notice_dates={'X':{self.day:'2025-06-06'}})
        corrected=corrected_actions(snapshots,correction)
        self.assertEqual(corrected[0],snapshots[0])
        self.assertEqual(corrected[1]['actions']['X'],event)
        self.assertEqual(corrected[1]['all_actions']['X'][self.day],event)
        self.assertEqual(corrected[2],snapshots[2])
        self.assertEqual(json.dumps(snapshots,sort_keys=True),original)
        correction['notice_dates']['X'][self.day]='2025-06-17'
        with self.assertRaisesRegex(ValueError,'not yet available'):
            corrected_actions(snapshots,correction)

if __name__=='__main__':unittest.main()
