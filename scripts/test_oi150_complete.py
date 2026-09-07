#!/usr/bin/env python3
"""Data and decision boundary checks for OI-150's frozen study."""
import sys
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'experimental'))
import oi150_complete as study


class StudyTests(unittest.TestCase):
    def test_future_and_undated_facts_excluded_including_dei(self):
        entries = [dict(filed='2010-04-30', val=1), dict(filed='2010-05-01', val=2), dict(val=3)]
        facts = {tax: {'X': {'units': {'shares': entries}}} for tax in ('us-gaap','dei')}
        got = study.filtered_facts(facts, '2010-04-30')
        for tax in facts:
            self.assertEqual(got[tax]['X']['units']['shares'], entries[:1])
        self.assertEqual(len(facts['dei']['X']['units']['shares']), 3)

    def test_spearman_ties_are_order_invariant(self):
        pairs = [(1, 10), (1, 20), (2, 30), (2, 40)]
        self.assertAlmostEqual(study.rank_correlation(pairs), .8944271909999159)
        self.assertAlmostEqual(study.rank_correlation(pairs), study.rank_correlation(list(reversed(pairs))))
        self.assertIsNone(study.rank_correlation([(1, 2), (1, 3)]))
        self.assertIsNone(study.rank_correlation([]))

    def test_unverified_early_end_is_not_delisting(self):
        days = ['2010-04-30','2011-04-29']
        tr = dict(zip(days, [100, 120]))
        self.assertEqual(study.forward(tr, days, days[0], 3, []), (None, 'unverified_terminal_or_gap'))
        value, kind = study.forward(tr, days, days[0], 3, ['2011-05-05'])
        self.assertEqual(kind, 'delisted_terminal')
        self.assertAlmostEqual(value, 1.2**(1/3)-1)

    def test_late_future_target_never_treated_as_delisting(self):
        days = ['2024-04-30','2025-04-30']
        self.assertEqual(study.forward(dict(zip(days,[100,110])), days, days[0], 3, ['2025-05-05']),
                         (None,'window_incomplete'))

    def test_gap_inside_series_does_not_use_later_terminal(self):
        days = ['2010-04-30','2011-04-29','2016-01-01']
        self.assertEqual(study.forward(dict(zip(days,[100,110,200])), days, days[0],3,['2016-01-02']),
                         (None,'unverified_terminal_or_gap'))

    def test_full_window(self):
        days=['2010-04-30','2013-04-30']
        value,kind=study.forward(dict(zip(days,[100,133.1])),days,days[0],3,[])
        self.assertEqual(kind,'full')
        self.assertAlmostEqual(value,.1)

    def test_unclassified_bucket_cannot_pass_as_zero_missing(self):
        lo,hi=study.missing_bounds(10,0,10)
        self.assertEqual(lo,0)
        self.assertEqual(hi,.5)
        self.assertEqual(study.missing_bounds(0,0,0),(None,None))

    def test_inference_uses_only_preregistered_ratios(self):
        prices=[('2010-04-29',60.),('2010-04-30',10.)]
        shares=[('2010-03-31',100.),('2010-06-30',600.)]
        self.assertEqual(study.old.inferred_splits(prices,shares,[],ratios=(2,3,4,5,7,10,20)),[])
        self.assertEqual(study.old.inferred_splits(prices,shares,[]),[('2010-04-30',6.)])

    def test_original_universe_exact(self):
        obs=study.observations()
        self.assertEqual(len(obs),653)
        self.assertEqual(sum(map(len,obs.values())),52800)
        self.assertEqual(min(d for ds in obs.values() for d in ds),'2010-04-30')
        self.assertEqual(max(d for ds in obs.values() for d in ds),'2021-03-31')

    def test_data_gate_overrides_numerically_passing_result(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            p.joinpath('manifest.json').write_text(json.dumps({'inputs':{}}))
            rows=[]
            obs={}
            for i,pv in enumerate((.4,.9,1.1,1.4,1.8,2.2,3.,5.)):
                c=str(i)
                obs[c]=[]
                for y in study.GROUPS:
                    day=f'{y}-04-30';obs[c].append(day)
                    rows.append(dict(cik=c,date=day,status='ok',price='100',pv=str(pv),
                                     max_filed=day,fwd3=str(.1+.1/pv),fwd5=str(.1+.1/pv),
                                     kind3='full',kind5='full',action_warning=''))
            study.save_csv(p/'pv_monthly.csv',rows)
            study.save_csv(p/'price_sources.csv',[dict(cik=str(i),status='ok') for i in range(8)])
            study.save_csv(p/'corporate_action_audit.csv',[dict(split_conflicts=0,split_missing=0)])
            study.save_csv(p/'universe_pit_audit.csv',[dict(status='filed_after_entry')])
            with patch.object(study,'EXP',p),patch.object(study,'observations',return_value=obs),patch('builtins.print'):
                study.report()
            result=json.loads((p/'result.json').read_text())
            self.assertTrue(result['horizons']['3']['descriptive_criteria_pass'])
            self.assertTrue(result['horizons']['5']['descriptive_criteria_pass'])
            self.assertEqual(result['outcome'],'不可判')
            # Duplicate company-months must fail, not silently inflate the denominator.
            study.save_csv(p/'pv_monthly.csv',rows+[rows[0]])
            with patch.object(study,'EXP',p),patch.object(study,'observations',return_value=obs):
                with self.assertRaises(AssertionError):study.report()

    def test_frame_repeated_value_is_not_future_information(self):
        with tempfile.TemporaryDirectory() as d:
            raw=Path(d);(raw/'frames').mkdir()
            e=dict(cik=1,val=100,start='2009-01-01',end='2009-12-31',accn='late')
            (raw/'frames/Revenues_CY2009.json').write_text(json.dumps({'data':[e]}))
            u=dict(cik='0000000001',cy='2009',revenue='100',obs_from='2010-04-30')
            early=dict(e,filed='2010-03-01',accn='early')
            late=dict(e,filed='2012-03-01')
            facts={'us-gaap':{'Revenues':{'units':{'USD':[early,late]}}}}
            with patch.object(study,'RAW',raw),patch.object(study,'csv_rows',return_value=[u]),patch.object(study.old,'REV_CONCEPTS',('Revenues',)):
                got=study.frame_audit('0000000001',facts)[0]
            self.assertEqual(got['status'],'available')
            self.assertEqual(got['filed'],'2010-03-01')
            self.assertEqual(got['source_filed'],'2012-03-01')
            # A restated amount unavailable at entry must remain flagged.
            early['val']=90
            with patch.object(study,'RAW',raw),patch.object(study,'csv_rows',return_value=[u]),patch.object(study.old,'REV_CONCEPTS',('Revenues',)):
                got=study.frame_audit('0000000001',facts)[0]
            self.assertEqual(got['status'],'filed_after_entry')


if __name__ == '__main__':
    unittest.main()
