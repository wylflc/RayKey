"""Boundary checks for historical top-three calendar windows and membership periods."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent/'experimental'))
from top3_period_forward import (anniversary, forward, membership_segments, nonoverlap_calendar,
                                stop_latched_eligibility, ma60_counting_episodes)


class Top3Checks(unittest.TestCase):
    def test_leap_anniversary(self):
        self.assertEqual(anniversary('2020-02-29',1),'2021-02-28')
        self.assertEqual(anniversary('2020-02-29',3),'2023-02-28')

    def test_weekend_and_return(self):
        days=['2020-01-03','2021-01-04']
        r=forward({'execution_date':'2020-01-03'},1,days,
                  {'2020-01-03':10,'2021-01-04':12}, {'2020-01-03':1,'2021-01-04':1.25})
        self.assertEqual(r['target_1y'],'2021-01-03')
        self.assertEqual(r['end_1y'],'2021-01-04')
        self.assertEqual(r['return_1y'],.25)

    def test_missing_execution_not_delayed(self):
        r=forward({'execution_date':'2020-01-03'},1,['2020-01-03','2021-01-04'],
                  {'2020-01-06':10,'2021-01-04':12},{'2020-01-06':1,'2021-01-04':1.2})
        self.assertEqual(r['status_1y'],'execution_quote_missing')
        self.assertEqual(r['return_1y'],'')

    def test_missing_endpoint_not_delayed(self):
        r=forward({'execution_date':'2020-01-03'},1,['2020-01-03','2021-01-04','2021-01-05'],
                  {'2020-01-03':10,'2021-01-05':12},{'2020-01-03':1,'2021-01-05':1.2})
        self.assertEqual(r['status_1y'],'endpoint_quote_missing')

    def test_short_history_not_zero(self):
        r=forward({'execution_date':'2020-01-03'},3,['2020-01-03','2021-01-04'],
                  {'2020-01-03':10,'2021-01-04':12},{'2020-01-03':1,'2021-01-04':1.2})
        self.assertEqual(r['status_3y'],'forward_incomplete')
        self.assertEqual(r['return_3y'],'')

    def test_membership_not_rank_or_price(self):
        days=['2020-01-02','2020-01-03','2020-01-06','2020-01-07']
        def picks(codes):
            return [{'security_code':c,'rank':i,'eligible_count':len(codes)} for i,c in enumerate(codes,1)]
        result=membership_segments(days,{days[0]:picks(['a','b','c']), days[1]:picks(['c','b','a']),
                                         days[2]:picks(['a','b','d'])})
        self.assertEqual(len(result),9)
        self.assertEqual(result[0]['segment_end'],days[1])
        self.assertEqual(result[0]['security_code'],'a')
        self.assertEqual(result[6]['security_code'],'')

    def test_nonoverlap_reserves_incomplete_horizon(self):
        rows=[{'execution_date':'2020-01-01','end_1y':'','target_1y':'2021-01-01'},
              {'execution_date':'2020-08-01','end_1y':'','target_1y':'2021-08-01'},
              {'execution_date':'2021-01-01','end_1y':'2022-01-03','target_1y':'2022-01-01'}]
        self.assertEqual(nonoverlap_calendar(rows,1),[rows[0],rows[2]])


class LatchedChecks(unittest.TestCase):
    def run_case(self, values, cheap=None, actions=None):
        days=[f'2020-01-{i+1:02d}' for i in range(len(values))]
        prices={d:v[0] for d,v in zip(days,values)}
        ma={d:{20:v[1],60:v[2]} for d,v in zip(days,values)}
        eligible,cycles=stop_latched_eligibility(days,prices,ma,
                                                set(days if cheap is None else [days[i] for i in cheap]),actions or {})
        return days,eligible,cycles

    def test_retrace_pause_resume_stop_and_reactivation(self):
        days,e,c=self.run_case([(12,11,10),(10.8,11.2,10.2),(10.5,10,10.3),
                               (10.4,10.6,10.3),(10.1,10.5,10.4),(10.5,10.8,10.1),(11.5,10.8,10.1)])
        self.assertEqual(list(e),[days[i] for i in (0,1,3,6)])
        self.assertEqual(e[days[3]]['activation_date'],days[0])
        self.assertEqual(e[days[3]]['stop_line'],10.2)
        self.assertEqual(c[0]['reset_date'],days[4])
        self.assertEqual(c[1]['activation_date'],days[6])

    def test_valuation_gap_only_pauses(self):
        days,e,c=self.run_case([(12,11,10),(10.8,11.2,10.2),(10.5,10.8,10.3)],cheap=[0,2])
        self.assertEqual(list(e),[days[0],days[2]])
        self.assertEqual(len(c),1)

    def test_unqualified_price_signal_does_not_activate(self):
        _,e,c=self.run_case([(12,11,10),(10.8,11.2,10.2)],cheap=[1])
        self.assertEqual(e,{})
        self.assertEqual(c,[])

    def test_stop_tracked_while_outside_pool(self):
        days,e,c=self.run_case([(12,11,10),(10.8,11.2,10.2),(9.5,10.5,10.1),
                               (10.4,10.6,10.2)],cheap=[0,3])
        self.assertEqual(list(e),[days[0]])
        self.assertEqual(c[0]['reset_date'],days[2])

    def test_equality_does_not_reset(self):
        _,e,c=self.run_case([(12,11,10),(11,11.2,10),(10,10.8,10.5)])
        self.assertEqual(len(e),3)
        self.assertEqual(c[0]['reset_date'],'')

    def test_cash_and_bonus_adjust_anchor(self):
        days,e,c=self.run_case([(12,11,10),(12,11,10),(5.5,5.8,4.8)],
                              actions={'2020-01-03':(1,1,0,0)})
        self.assertEqual(e[days[2]]['stop_anchor'],4.5)
        self.assertEqual(c[0]['reset_date'],'')

    def test_signal_day_never_reads_next_ma(self):
        days,e,c=self.run_case([(12,11,10),(11,10.5,10.2)])
        self.assertEqual(e[days[0]]['stop_anchor'],'')
        self.assertEqual(e[days[1]]['anchor_date'],days[1])
        self.assertEqual(e[days[1]]['stop_anchor'],10.2)

    def test_single_last_day_signal_remains(self):
        days,e,c=self.run_case([(12,11,10)])
        self.assertEqual(e[days[0]]['qualification'],'initial')
        self.assertEqual(c[0]['anchor_date'],'')

    def test_below_ma60_counting_closes_same_day(self):
        result=ma60_counting_episodes([True,True,True],[9,11,12],[10,10,10])
        self.assertEqual([r['signal_i'] for r in result],[0,1])
        self.assertEqual(result[0]['break_i'],0)
        self.assertIsNone(result[1]['break_i'])


if __name__=='__main__':
    unittest.main()
