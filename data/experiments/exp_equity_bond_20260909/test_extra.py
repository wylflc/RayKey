"""Additional policy invariants, kept with the frozen experiment."""
import csv
import copy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'scripts'))
import backtest_valuation_strategy as bt
from test_equity_bond_constraint import EquityBondTest
import unittest


class ExtraTest(EquityBondTest):
    def test_proportionate_sales_and_tax(self):
        p=self.portfolio()
        p.lots['B']=copy.deepcopy(p.lots['A']);p.lots['B'].code='B'
        p.lots['B'].shares=8000.
        p.debt=90000.
        bt.DIVIDEND_TAX_ON=True
        p.lots['A'].sublots=[['2024-01-01',16000.,3200.]]
        p.lots['B'].sublots=[['2024-01-01',8000.,1600.]]
        bt.SLIPPAGE=.003
        try:
            ledger=[]
            bt.enforce_equity_bond_cap(p,'2024-01-10',{'A':10.,'B':10.},lambda c,_:10.,.8,100,ledger,{})
            self.assertGreater(p.dividend_tax_paid,0.)
            self.assertEqual(p.debt,0.)
            self.assertLessEqual(p.gross({'A':10.,'B':10.})-p.cash,.8*p.equity({'A':10.,'B':10.})+1e-6)
            self.assertLess(abs(p.lots['A'].shares-2*p.lots['B'].shares),401.)
            self.assertTrue(all(abs(float(r['price'])-9.97)<1e-9 for r in ledger))
        finally:bt.SLIPPAGE=0.

    def test_appended_future_observation_does_not_change_history(self):
        rows=[('2023-10-31',10),('2023-11-30',20),('2023-12-29',15)]
        a=self.signal(rows)
        b=self.signal(rows+[('2024-01-31',1000)])
        self.assertEqual(a.resolve('2024-01-02'),b.resolve('2024-01-02'))


if __name__=='__main__':unittest.main()
