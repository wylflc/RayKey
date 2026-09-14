"""Counting must not depend on future returns, temporary PV or MA20 changes."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent/'experimental'))
from pv_episode_forward import episodes, nonoverlap, return_indices


class EpisodeTest(unittest.TestCase):
    def test_only_ma60_break_rearms(self):
        prices = [11, 12, 11, 12, 9, 11, 12]
        found = episodes([True, True, False, True, False, True, True], prices, [10]*7, [[] for _ in prices])
        self.assertEqual([e['signal_i'] for e in found], [0, 5])
        self.assertEqual(found[0]['break_i'], 4)

    def test_entry_anchor_and_current_ma_are_different(self):
        p = [11, 12, 11, 12]
        eligible = [True, True, False, True]
        ma = [10, 10, 11.5, 11]
        self.assertEqual(len(episodes(eligible,p,ma,[[]]*4)), 2)
        self.assertEqual(len(episodes(eligible,p,ma,[[]]*4,'stop')), 1)

    def test_anchor_adjusts_after_execution_not_on_execution(self):
        ep = episodes([True, False, False, True], [11,11,5.5,6], [10,10,6,5.5],
                      [[],[],[(0,1,0,0)],[]], 'stop')
        self.assertEqual(len(ep), 1)
        self.assertEqual(ep[0]['anchor'], 5)

    def test_strict_windows_do_not_overlap_and_no_synthetic_entry(self):
        events = [{'exec_i': i} for i in [1, 20, 250, 251, 400, 502]]
        self.assertEqual([e['exec_i'] for e in nonoverlap(events,250)], [1,251,502])

    def test_dividend_rights_split_self_financing(self):
        tri,s,c=return_indices(['a','b'], [10,4], {'b':(1,1,.5,2)})
        self.assertEqual(tri,[1,1])
        self.assertEqual(s[-1]*4+c[-1],10)

    def test_suspended_event_and_future_events(self):
        tri,_,_=return_indices(['a','c'], [10,5], {'b':(0,1,0,0),'z':(100,0,0,0)})
        self.assertEqual(tri,[1,1])

    def test_reinvestment_and_cash_are_distinct(self):
        tri,s,c=return_indices(['a','b','c'], [10,9,18], {'b':(1,0,0,0)})
        self.assertAlmostEqual(tri[-1]/tri[0]-1,1)
        self.assertAlmostEqual((s[-1]*18+c[-1])/10-1,.9)
        self.assertAlmostEqual(tri[-1]/tri[1]-1,1)


if __name__ == '__main__':
    unittest.main()
