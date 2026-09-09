"""Reject incomplete comparisons and apply the written zero-to-positive veto."""
import copy
import unittest
from analyze import validate_pair, checked_verdict, sw


class AnalysisTest(unittest.TestCase):
    def test_missing_adverse_window_rejected(self):
        base = {s:{'首个净值日':'2010-01-01','末次净值日':'2026-08-28',
                   sw.WIN5_KEY:'2020-01=0.1;2020-02=0.1', '年化':'.1','最大回撤':'.3',
                   '滚动5年回撤中位':'.3','滚动5年为负的窗口占比':'0'} for s in sw.DEFAULT_STARTS}
        arm = copy.deepcopy(base)
        validate_pair(arm,base)
        arm[sw.DEFAULT_STARTS[0]][sw.WIN5_KEY] = '2020-01=0.2'
        with self.assertRaises(AssertionError):
            validate_pair(arm,base)

    def test_missing_start_rejected(self):
        with self.assertRaises(AssertionError):
            validate_pair({}, {})

    def test_veto_only_zero_to_positive(self):
        def groups(base_negative, arm_negative):
            base = {s:{'年化':.1,sw.WIN5_KEY:{'2020-01':.1},'最大回撤':.3,
                       '滚动5年年化最差':.1,'滚动5年回撤中位':.3,
                       '滚动5年为负的窗口占比':base_negative} for s in sw.DEFAULT_STARTS}
            arm = {s:dict(r,年化=.12, **{sw.WIN5_KEY:{'2020-01':.12},
                       '滚动5年为负的窗口占比':arm_negative}) for s,r in base.items()}
            return dict(BASE=base,C=arm)
        g = groups(.01,.02)
        self.assertEqual(checked_verdict(g,g,'C')[0], '可采纳')
        g = groups(0,.02)
        self.assertEqual(checked_verdict(g,g,'C')[0], '不采纳')
        for s in sw.DEFAULT_STARTS[7:]:
            g['C'][s]['滚动5年为负的窗口占比'] = 0
        self.assertEqual(checked_verdict(g,g,'C')[0], '可采纳')


if __name__ == '__main__':
    unittest.main()
