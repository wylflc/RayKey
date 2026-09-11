import unittest
from unittest.mock import patch
import math
import numpy as np
from common import ROOT
from policy import RiskPolicy, ReturnPanel, combine


class RiskTests(unittest.TestCase):
    def panel(self):
        dates=[f'{i:04}' for i in range(100)]
        return ReturnPanel({'A':dict(zip(dates,[.01,-.01]*50)),
                            'B':dict(zip(dates,[-.01,.01]*50))},dates)

    def test_diversification_and_normalization(self):
        p=self.panel()
        risk,_=p.risk({'A':.5,'B':.5},'0099',[20,60]);self.assertAlmostEqual(risk,0)
        r=RiskPolicy(dict(kind='vol',target=.3,floor=1.,windows=[20,60]))
        r.observe('0098',{'A':300.,'B':100.},p)
        before=r.resolve('0098')
        r.observe('0099',{'A':3000.,'B':1000.},p)
        self.assertEqual(before,r.resolve('0099'))

    def test_no_future_returns(self):
        p=self.panel();before=p.risk({'A':1},'0070',[20,60])
        p.values[71:,:]=1000
        self.assertEqual(before,p.risk({'A':1},'0070',[20,60]))

    def test_future_holdings_rejected(self):
        r=RiskPolicy(dict(kind='stress',budget=.24));r.observe('2020-01-02',{'A':1},None)
        with self.assertRaises(AssertionError):r.resolve('2020-01-01')

    def test_pressure_and_recovery(self):
        r=RiskPolicy(dict(kind='stress',budget=.24))
        r.observe('1',{'A':1},None);self.assertEqual(r.resolve('1'),1.2)
        r.observe('2',{str(i):1 for i in range(10)},None)
        self.assertEqual(r.resolve('2'),1.3)
        r.observe('3',{str(i):1 for i in range(10)},None)
        self.assertEqual(r.resolve('3'),1.4)

    def test_missing_coverage_deleverages(self):
        p=self.panel();p.observed[-20:,0]=False
        r=RiskPolicy(dict(kind='vol',target=.3,floor=1.,windows=[20,60]))
        r.observe('0099',{'A':1},p);self.assertEqual(r.resolve('0099'),1.)
        self.assertTrue(r.last['missing'])

    def test_cash_only_vol_has_no_cap(self):
        r=RiskPolicy(dict(kind='vol',target=.3,floor=1.,windows=[20,60]))
        self.assertIsNone(r.resolve('1'))

    def test_c030_always_stricter(self):
        self.assertEqual(combine(.3,1.2),.3)
        self.assertEqual(combine(None,1.2),1.2)
        self.assertIsNone(combine(None,None))

    def test_adjusted_returns(self):
        import backtest_valuation_strategy as bt
        r=bt.daily_returns({'A':{'1':20.,'2':10.}}, {'A':{'2':(0.,1.,0.,0.)}})
        self.assertEqual(r['A']['2'],0.)

    def test_buy_cap_includes_fees(self):
        import backtest_valuation_strategy as bt
        p=bt.Portfolio(cash=3000000)
        with patch.dict(bt.FEES,commission=.0001,min_fee=5.):
            q=bt.equity_bond_buy_shares(p,{},500000,10.,10.,'2024-01-02',100,0.,1.)
            self.assertLess(q,300000)
            self.assertLessEqual(q*10, p.cash-bt._fee_quiet(q*10,'2024-01-02','buy'))

    def test_disabled_and_fixed(self):
        self.assertIsNone(RiskPolicy(dict(kind='off')).resolve('1'))
        self.assertEqual(RiskPolicy(dict(kind='fixed',cap=1.4)).resolve('1'),1.4)


if __name__=='__main__':unittest.main()
