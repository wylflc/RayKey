"""Economic invariants and time-availability tests for the temperature study."""
import sys
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent / 'experimental'))
from cbbi_temperature import (total_return_frame, past_month_rank, measure_forward,
                              stocks_valuation, features, sample_masks)
from corporate_actions import CorporateAction, event_map


def quotes(days, prices, volumes=None):
    volumes = volumes if volumes is not None else [100.] * len(days)
    return [dict(date=d,open=p,close=p,high=p,low=p,volume=v,turnover_pct=1)
            for d,p,v in zip(days,prices,volumes)]


class EconomicTests(unittest.TestCase):
    def test_dividend_and_split_are_not_a_crash(self):
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[100,49],[100,200]),
                              {'2020-01-03':(2,1,0,0)})
        self.assertAlmostEqual(df.total_return.iloc[-1],100)
        self.assertAlmostEqual(df.volume_units.iloc[0],df.volume_units.iloc[-1])

    def test_actual_cash_and_exchange_price_terms_are_distinct(self):
        action=CorporateAction((2,0,0,0),(1.9,0,0,0))
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[100,98.1]),{'2020-01-03':action})
        self.assertAlmostEqual(df.total_return.iloc[-1],100.1)

    def test_rights_are_not_free_shares(self):
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[100,110/1.2]),
                              {'2020-01-03':(0,0,.2,50)})
        self.assertAlmostEqual(df.total_return.iloc[-1],100)

    def test_suspension_accumulates_cash_without_phantom_reinvestment(self):
        # Cash of 2 is paid before a 2-for-1 split; another 1 per new share follows.
        actions={'2020-01-03':(2,0,0,0),'2020-01-06':(0,1,0,0),'2020-01-07':(1,0,0,0)}
        df=total_return_frame(quotes(['2020-01-02','2020-01-08'],[100,48]),actions)
        self.assertAlmostEqual(df.total_return.iloc[-1],100)

    def test_reverse_split(self):
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[20,100],[100,20]),
                              {'2020-01-03':(0,-.8,0,0)})
        self.assertAlmostEqual(df.total_return.iloc[-1],100)
        self.assertAlmostEqual(df.volume_units.iloc[-1],100)

    def test_first_quote_is_already_ex_distribution(self):
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[49,49]),
                              {'2020-01-02':(2,1,0,0)})
        np.testing.assert_allclose(df.total_return,[100,100])

    def test_future_actions_do_not_change_past_ma_or_returns(self):
        days=pd.bdate_range('2010-01-01',periods=100).strftime('%Y-%m-%d').tolist()
        rows=quotes(days,[100.]*80+[49.]*20)
        actions={days[80]:(2,1,0,0)}
        full=total_return_frame(rows,actions)
        prefix=total_return_frame(rows[:75],{})
        np.testing.assert_allclose(prefix.total_return,full.total_return.iloc[:75])
        np.testing.assert_allclose(prefix.ma60_price_basis,full.ma60_price_basis.iloc[:75],equal_nan=True)

    def test_duplicate_same_plan_not_double_counted(self):
        row=dict(security_code='TEST',ex_dividend_date='2020-01-03',report_date='2019-12-31',
                 plan_notice_date='2020-01-01',cash_per_share=2,share_ratio=1,rights_ratio=0,rights_price=0)
        actions=event_map([row,row])['TEST']
        df=total_return_frame(quotes(['2020-01-02','2020-01-03'],[100,49]),actions)
        self.assertAlmostEqual(df.total_return.iloc[-1],100)


class AvailabilityTests(unittest.TestCase):
    def test_rank_excludes_current_month_and_uses_midrank(self):
        s=pd.Series([10,20,30,20,1000],index=['2020-01-31','2020-02-28','2020-03-31','2020-04-01','2020-04-30'])
        result=past_month_rank(s,lookback=3,minimum=3)
        self.assertEqual(result.iloc[3],50)
        self.assertEqual(result.iloc[4],100)
        self.assertTrue(np.isnan(result.iloc[2]))

    def test_partial_month_append_does_not_change_old_scores(self):
        days=pd.bdate_range('2015-01-01',periods=450).strftime('%Y-%m-%d')
        s=pd.Series(np.arange(len(days)),index=days)
        a=past_month_rank(s,6,3);b=past_month_rank(s.iloc[:410],6,3)
        np.testing.assert_allclose(a.iloc[:410],b,equal_nan=True)

    def test_missing_month_end_is_not_replaced_by_earlier_quote(self):
        s=pd.Series([10,20,30,np.nan,25],index=['2020-01-31','2020-02-28','2020-03-30','2020-03-31','2020-04-01'])
        self.assertTrue(np.isnan(past_month_rank(s,3,3).iloc[-1]))

    def test_notice_day_is_not_available_and_split_shares_match(self):
        reports=[dict(report_date='2019-12-31',notice_date='2020-03-10',parent_netprofit=100)]
        shares=[dict(effective_date='2019-01-01',total_shares=10),dict(effective_date='2020-03-12',total_shares=20)]
        bonds=[dict(observed_on='2020-03-09',bond_yield=.03)]
        result=stocks_valuation(['2020-03-10','2020-03-11','2020-03-12'],[100,100,50],reports,shares,bonds)
        self.assertTrue(np.isnan(result.valuation_raw.iloc[0]))
        self.assertAlmostEqual(result.valuation_raw.iloc[1],-.07)
        self.assertAlmostEqual(result.valuation_raw.iloc[2],-.07)

    def test_ttm_requires_all_three_published_periods(self):
        reports=[dict(report_date='2019-12-31',notice_date='2020-03-10',parent_netprofit=100),
                 dict(report_date='2020-03-31',notice_date='2020-04-10',parent_netprofit=50)]
        r=stocks_valuation(['2020-04-13'],[100],reports,[dict(effective_date='2019-01-01',total_shares=10)],
                           [dict(observed_on='2020-04-10',bond_yield=.03)])
        self.assertTrue(np.isnan(r.valuation_raw.iloc[0]))

    def test_forward_starts_next_market_close_and_retains_missing(self):
        days=['2020-01-02','2020-01-03','2020-02-03','2020-03-03']
        frame=pd.DataFrame({'total_return':[100,120,180,240]},index=days)
        result=measure_forward(frame,days,1)
        self.assertAlmostEqual(result.loc['2020-01-02','forward_return'],.5)
        self.assertEqual(result.loc['2020-03-03','status'],'unmatured')
        missing=measure_forward(frame.drop('2020-01-03'),days,1)
        self.assertEqual(missing.loc['2020-01-02','status'],'missing_execution_quote')


if __name__=='__main__':unittest.main()
