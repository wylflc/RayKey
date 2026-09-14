import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from slope import SlopeGuard
from engine import install,bt

S={'lag':1,'windows':[20,60]}
class SlopeTest(unittest.TestCase):
    def guard(self,ma,actions=None,spec=S):
        return SlopeGuard({'x':{d:1 for d in ma}},{'x':ma},{'x':actions or {}},spec)
    def test_both_required(self):
        ma={'a':{20:10,60:9},'b':{20:11,60:8},'c':{20:12,60:9}}
        g=self.guard(ma);self.assertFalse(g.allows('x','b'));self.assertTrue(g.allows('x','c'))
    def test_flat_is_not_positive(self):
        self.assertFalse(self.guard({'a':{20:10,60:9},'b':{20:10,60:10}}).allows('x','b'))
    def test_dividend_bonus_rights_rebase(self):
        # Previous 20/60 MAs 10/8 become 4/3.2 after 1 cash, 100% bonus, .5 rights @2.
        g=self.guard({'a':{20:10,60:8},'b':{20:4.1,60:3.3}},{'b':(1,1,.5,2)})
        self.assertTrue(g.allows('x','b'))
    def test_action_in_suspension_and_future_action(self):
        g=self.guard({'a':{20:10,60:8},'c':{20:5.1,60:4.1}},{'b':(0,1,0,0),'z':(100,0,0,0)})
        self.assertTrue(g.allows('x','c'));self.assertEqual(g.rebase('x',10,'a','c'),5)
    def test_future_prices_do_not_affect_past_signal(self):
        a={'a':{20:10,60:9},'b':{20:11,60:10}}
        self.assertEqual(self.guard(a).allows('x','b'),self.guard({**a,'z':{20:0,60:0}}).allows('x','b'))
    def test_missing_history_rejected(self):
        self.assertFalse(self.guard({'a':{20:10,60:9}}).allows('x','a'))
    def test_lag_definition(self):
        g=self.guard({'a':{20:10,60:9},'b':{20:15,60:15},'c':{20:12,60:10}},spec={'lag':2,'windows':[20,60]})
        self.assertTrue(g.allows('x','c'))
    def test_base_native_and_unique_insertion(self):
        old=bt.run;install({'lag':0,'windows':[]});self.assertIs(bt.run,old)
        install(S);self.assertIsNot(bt.run,old);bt.run=old

if __name__=='__main__':unittest.main()
