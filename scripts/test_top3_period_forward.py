"""Boundary checks for historical top-three calendar windows and membership periods."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent/'experimental'))
from top3_period_forward import anniversary, forward, membership_segments, nonoverlap_calendar


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


if __name__=='__main__':
    unittest.main()
