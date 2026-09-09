"""Timing, exposure, repayment, fee/lot and suspension checks for the research overlay."""
import csv
from pathlib import Path
import tempfile
import unittest
import backtest_valuation_strategy as bt
from equity_bond_constraint import EquityBondConstraint
from test_buy_top_pct import fixture, row


class EquityBondTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'signal.csv'
        self.fees = dict(bt.FEES)
        self.tax = bt.DIVIDEND_TAX_ON
        bt.DIVIDEND_TAX_ON = False
        bt.FEES.update({'commission': .0001, 'min_fee': 5., 'stamp': .0005, 'transfer': .00001, 'paid': 0.})
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda: (bt.FEES.clear(), bt.FEES.update(self.fees), setattr(bt, 'DIVIDEND_TAX_ON', self.tax)))

    def signal(self, rows=None, **kw):
        rows = rows or [('2024-01-02', 10), ('2024-01-05', 100)]
        with self.path.open('w') as f:
            w=csv.writer(f);w.writerow(['observed_on','pe_ttm','bond_yield','bond_observed_on'])
            for d,pe in rows: w.writerow([d,pe,.02,d])
        return EquityBondConstraint(self.path, metric='spread', threshold=.03, lower=1., **kw)

    def test_past_only_percentile_and_ties(self):
        self.signal([('2023-10-31',10),('2023-11-30',20),('2023-12-29',10),('2024-01-02',5)])
        s=EquityBondConstraint(self.path, window=2, min_obs=2)
        self.assertIsNone(s.resolve('2023-11-30')[1])
        self.assertEqual(s.resolve('2023-12-29')[0].percentile,.75)
        self.assertEqual(s.resolve('2024-01-02')[0].percentile,1.)
        self.assertEqual(s.resolve('2023-12-30')[0].observed_on,'2023-12-29')

    def test_invalid_stale_duplicate_and_units(self):
        for rows in ([('2024-01-02',0)], [('2024-01-02',10),('2024-01-02',20)]):
            with self.assertRaises(ValueError):self.signal(rows)
        s=self.signal()
        self.assertEqual(s.resolve('2023-12-29'),(None,None))
        with self.assertRaises(ValueError):s.resolve('2024-03-01')
        self.path.write_text('observed_on,pe_ttm,bond_yield,bond_observed_on\n2024-01-02,10,2,2024-01-03\n')
        with self.assertRaises(ValueError):EquityBondConstraint(self.path)

    def test_cap_range_and_ramp(self):
        self.signal()
        for kw in ({'upper':1.7},{'lower':-1},{'threshold':float('nan')},{'min_obs':61}):
            with self.assertRaises(ValueError): EquityBondConstraint(self.path,**kw)
        s=EquityBondConstraint(self.path,mode='ramp',threshold=.2,ramp_high=.8, min_obs=1)
        self.assertEqual(s.resolve('2024-01-05')[1],0.)

    def portfolio(self):
        p=bt.Portfolio(cash=0.,debt=60000.)
        lot=bt.Lot(code='A',entry_date='2023-01-01',shares=16000.,avg_cost=10.,invested=160000.,
                   entry_ratio=.8,entry_value=12.5,entry_band_low=10.,entry_band_high=15.,entry_upside=.25)
        p.lots['A']=lot
        return p

    def test_active_cap_repays_and_counts_fees(self):
        p=self.portfolio(); ledger=[]
        turnover,n=bt.enforce_equity_bond_cap(p,'2024-01-02',{'A':10.},lambda c,_:10.,1.,100,ledger,{})
        self.assertGreater(turnover,60000.)
        self.assertGreater(n,0)
        self.assertEqual(p.debt,0.)
        self.assertLessEqual(p.gross({'A':10.})-p.cash,p.equity({'A':10.})+1e-6)
        self.assertTrue(all(int(r['shares'])%100==0 for r in ledger))

    def test_zero_cap_and_suspended_marks(self):
        p=self.portfolio()
        self.assertEqual(bt.enforce_equity_bond_cap(p,'2024-01-02',{'A':10.},lambda c,_:None,0.,100,[],{}),(0.,0))
        bt.enforce_equity_bond_cap(p,'2024-01-03',{'A':10.},lambda c,_:10.,0.,100,[],{})
        self.assertFalse(p.lots);self.assertEqual(p.debt,0.)

    def test_fee_and_lot_fallback_cannot_breach_cap(self):
        p=bt.Portfolio(cash=1000.)
        self.assertEqual(bt.equity_bond_buy_shares(p,{},100.,10.,10.,'2024-01-02',100,0,1.),0.)
        p.cash=10000.
        q=bt.equity_bond_buy_shares(p,{},2000.,10.1,10.,'2024-01-02',100,6000.,1.6)
        fee=bt._fee_quiet(q*10.1,'2024-01-02','buy')
        self.assertLessEqual(q*10.,1.6*(10000.-fee-q*.1))
        self.assertLessEqual(q*10.1+fee,16000.)

    def test_full_run_signal_delay_debt_and_default(self):
        days={d:[row('A',.8)] for d in ('2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09')}
        self.assertEqual(fixture(days),fixture(days,equity_bond=None))
        for mode in ('cap','credit'):
            s=self.signal(mode=mode)
            result,ledger=fixture(days,x=.8,credit_ratio=.666,credit_cap=1e12,lot_size=100,
                                  position_cap=0.,equity_bond=s,net_same_day=True)
            records={r['date']:r for r in result['equity_bond_records']}
            self.assertEqual(records['2024-01-05']['cap'],1.6)
            self.assertEqual(records['2024-01-08']['cap'],1.)
            self.assertTrue(all(r['cash']>=-1e-6 for r in records.values()))
            sales=[r for r in ledger if r['reason']=='股债·总仓位上限']
            if mode=='cap':
                self.assertTrue(sales)
                self.assertEqual(records['2024-01-08']['debt'],0.)
                self.assertTrue(all(not r['unresolved'] for r in records.values()))
            else:
                self.assertFalse(sales)
                self.assertGreater(records['2024-01-08']['debt'],0.)


    def test_restore_above_threshold_returns_no_cap(self):
        # v4.176 生产分支：利差 ≥ 阈值时 cap=None（不设上限、不改授信），< 阈值时 cap=lower；与 §12.220 high_base 子类等价
        rows=[('2024-01-02',10),('2024-01-05',100)]          # 1/10−.02=+8pp ≥ 3pp；1/100−.02=−1pp < 3pp
        plain=self.signal(rows, mode='cap'); restore=self.signal(rows, mode='cap', restore_above=True)
        self.assertEqual(plain.resolve('2024-01-03')[1], 1.6); self.assertIsNone(restore.resolve('2024-01-03')[1])
        self.assertEqual(plain.resolve('2024-01-08')[1], 1.); self.assertEqual(restore.resolve('2024-01-08')[1], 1.)
        self.assertEqual(restore.resolve('2024-01-08')[0].observed_on, '2024-01-05')
        days={d:[row('A',.8)] for d in ('2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08','2024-01-09')}
        result,_=fixture(days,x=.8,credit_ratio=.666,credit_cap=1e12,lot_size=100,position_cap=0.,equity_bond=restore,net_same_day=True)
        records={r['date']:r for r in result['equity_bond_records']}
        self.assertIsNone(records['2024-01-05']['cap'])          # 阈值以上：无上限（记录 cap 为空）
        self.assertEqual(records['2024-01-08']['cap'], 1.)

    def test_repayment_then_same_day_netting_funds_reversal(self):
        # A gain trim followed by an eligible add-on reverses part of the sale after repayment.
        for gain in (.01, .1, .3):
            days={d:[row('A',.8,price)] for d,price in
                  zip(('2024-01-02','2024-01-03','2024-01-04','2024-01-05','2024-01-08'),
                      (10.,10.,12.,12.,12.))}
            c=self.signal([('2024-01-02',10)])
            result,_=fixture(days,x=.3,credit_ratio=.666,credit_cap=1e12,lot_size=100,
                             gain_sell=gain,gain_sell_mode='ungated',equity_bond=c,net_same_day=True)
            self.assertTrue(all(r['cash']>=-1e-6 for r in result['equity_bond_records']))
            self.assertTrue(all(not r['unresolved'] for r in result['equity_bond_records']))


if __name__=='__main__':unittest.main()
