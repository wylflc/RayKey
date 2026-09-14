import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from slope import SlopeGuard
from engine import install,bt

S={'lag':1,'windows':[20,60]}
class SlopeTest(unittest.TestCase):
    def guard(self,prices=None,actions=None,spec=S):
        prices=prices or {f'd{i:03d}':10 for i in range(81)}
        return SlopeGuard({'x':prices},{},{'x':actions or {}},spec)
    def test_both_required(self):
        p={f'd{i:03d}':10 for i in range(82)};p.update(d080=11,d020=12,d081=12)
        g=self.guard(p);self.assertFalse(g.allows('x','d080'));self.assertTrue(g.allows('x','d081'))
    def test_flat_is_not_positive(self):
        self.assertFalse(self.guard().allows('x','d080'))
    def test_dividend_bonus_rights_rebase(self):
        p={f'd{i:03d}':10 for i in range(81)};p['d080']=4.1
        self.assertTrue(self.guard(p,{'d080':(1,1,.5,2)}).allows('x','d080'))
    def test_action_in_suspension_and_future_action(self):
        p={f'd{i:03d}':10 for i in range(81)};p['d080']=5.1
        g=self.guard(p,{'d0795':(0,1,0,0),'z':(100,0,0,0)})
        self.assertTrue(g.allows('x','d080'));self.assertEqual(g.rebase('x',10,'d079','d080'),5)
    def test_future_prices_do_not_affect_past_signal(self):
        p={f'd{i:03d}':10 for i in range(81)};p['d080']=11
        self.assertEqual(self.guard(p).allows('x','d080'),self.guard({**p,'z':0}).allows('x','d080'))
    def test_missing_history_rejected(self):
        self.assertFalse(self.guard({'a':10}).allows('x','a'))
    def test_lag_matches_explicit_rebased_window_means(self):
        p={f'd{i:03d}':10+i%7 for i in range(83)}
        g=self.guard(p,{'d0605':(1,.1,.2,2)},spec={'lag':3,'windows':[20,60]})
        ds=sorted(p);d=ds[-1]
        for n,(a,b,slope) in g.differences('x',d).items():
            current=sum(g.rebase('x',p[x],x,d) for x in ds[-n:])/n
            previous=sum(g.rebase('x',p[x],x,d) for x in ds[-n-3:-3])/n
            self.assertAlmostEqual(slope,(current-previous)/3,places=12)
    def test_base_native_and_unique_insertion(self):
        old=bt.run;install({'lag':0,'windows':[]});self.assertIs(bt.run,old)
        install(S);self.assertIsNot(bt.run,old);bt.run=old

if __name__=='__main__':unittest.main()
