import sys
import unittest
from common import ROOT, PRIOR, grid, load_module
sys.path.insert(0,str(PRIOR))
from policy import ResearchConstraint, compute_caps
from equity_bond_constraint import EquityBondConstraint, EquityBondSignal


class AdapterTest(unittest.TestCase):
    def test_baseline_aliases_preserve_native_signals(self):
        path=ROOT/'data/reference/equity_bond_csi300.csv'
        kw=dict(mode='cap',metric='spread',threshold=.03,lower=1.,restore_above=True)
        native=EquityBondConstraint(path,**kw)
        for spec in grid():
            if spec['kind']!='baseline':continue
            alias=ResearchConstraint(path,**kw,spec=spec)
            for day in reversed(native.days):
                self.assertEqual(native.resolve(day),alias.resolve(day))

    def test_center_release_and_restart_state(self):
        spec=next(r for r in grid() if r['arm']=='C030R35')
        signals=[EquityBondSignal(f'2020-{i+1:02}-28',v,None,i)
                 for i,v in enumerate((.036,.029,.031,.0349,.035,.031,.03,.029))]
        features=[dict(observed_on=s.observed_on) for s in signals]
        caps,_=compute_caps(signals,features,spec)
        self.assertEqual(caps,[None,.3,.3,.3,None,None,None,.3])
        path=ROOT/'data/reference/equity_bond_csi300.csv'
        c=ResearchConstraint(path,mode='cap',metric='spread',threshold=.03,
                             lower=1.,restore_above=True,spec=spec)
        answers={d:c.resolve(d) for d in c.days}
        for day in reversed(c.days):self.assertEqual(c.resolve(day),answers[day])

    def test_diagnostic_capture_preserves_output(self):
        from signals import instrument
        module=load_module('selection_capture_test',ROOT/'scripts/experimental/selection_edge_audit.py')
        original=module.daily_paired({'2020-01-01':([.2,.4],[.1])})
        instrument(module,lambda v:None)
        self.assertEqual(module.daily_paired({'2020-01-01':([.2,.4],[.1])}),original)


if __name__=='__main__':unittest.main()
