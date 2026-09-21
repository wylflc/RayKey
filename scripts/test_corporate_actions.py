"""Independent plans, same-day economics and fiscal availability (OI-196)."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import corporate_actions as ca
import build_historical_valuation_bands as bands
import backtest_valuation_strategy as bt
import divspread_dividend as div
import fetch_a_share_dividends as fetch
import fetch_ohlcv_history as history
from apply_holdings_corporate_action import event_from_actions
import code_succession

def component(report='2025-12-31', notice='2026-03-28', cash='.31', shares='0', **kwargs):
    return dict.fromkeys(ca.ACTION_FIELDS, '') | dict(security_code='300760', ex_dividend_date='2026-05-28',
              report_date=report, plan_notice_date=notice, cash_per_share=cash, share_ratio=shares) | kwargs

def raw(report='2025-12-31', cash=3.1, **kwargs):
    return dict(SECURITY_CODE='300760', REPORT_DATE=report, PLAN_NOTICE_DATE='2026-03-28',
                EX_DIVIDEND_DATE='2026-05-28', PRETAX_BONUS_RMB=cash, BONUS_RATIO=0, IT_RATIO=0) | kwargs

class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.rows = [component(), component('2026-03-31', '2026-04-29', '1.25')]

    def test_independent_plans_and_order_duplicates(self):
        expected = ca.unique_actions(self.rows)
        self.assertEqual(len(expected), 2)
        self.assertEqual(ca.unique_actions(self.rows[::-1] * 2), expected)
        self.assertEqual(ca.aggregate_actions(self.rows * 2)[0]['cash_per_share'], 1.56)

    def test_conflict_fails_before_overwrite(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            ca.unique_actions([self.rows[0], dict(self.rows[0], cash_per_share='.32')])

    def test_complete_refresh_replaces_proposal_and_corrected_date(self):
        proposal = dict(self.rows[0], ex_dividend_date='')
        unrelated = dict(self.rows[0], security_code='000651')
        rights = component(rights_ratio='.2', rights_price='4', cash='0')
        got = ca.merge_actions([proposal, unrelated, rights], self.rows)
        self.assertEqual(len(got), 4)
        self.assertIn(unrelated, got); self.assertIn(rights, got)
        corrected = [dict(r, ex_dividend_date='2026-05-29') for r in self.rows]
        self.assertEqual(ca.merge_actions(self.rows, corrected), ca.unique_actions(corrected))
        self.assertEqual(ca.merge_actions(self.rows, []), ca.unique_actions(self.rows))

    def test_same_day_split_addition_and_across_day_compounding(self):
        a = component(cash='0', shares='.2')
        b = component('2026-03-31', cash='0', shares='.8')
        self.assertEqual(bands.split_factor([a, b], '2026-01-01', '2026-06-01'), 2)
        b['ex_dividend_date'] = '2026-05-29'
        self.assertAlmostEqual(bands.split_factor([a, b], '2026-01-01', '2026-06-01'), 2.16)

    def test_cash_split_rights_share_common_pre_event_basis(self):
        rows = self.rows + [component(cash='0', shares='.4', report_date='2024-12-31'),
                           component(cash='0', rights_ratio='.2', rights_price='3'),
                           component('2026-03-31', cash='0', rights_ratio='.1', rights_price='6')]
        event = ca.aggregate_actions(rows)[0]
        self.assertAlmostEqual(event['rights_ratio'], .3)
        self.assertAlmostEqual(event['rights_price'], 4)
        price = (20-1.56+.2*3+.1*6)/(1+.4+.3)
        values, factor, cash = bands.exright_adjust(rows, '2026-01-01', '2026-06-01', (20,))
        self.assertAlmostEqual(values[0], price)
        self.assertEqual(ca.event_map(rows)['300760']['2026-05-28'], (1.56,.4,.3,4))
        self.assertEqual(ca.event_map(rows, False)['300760']['2026-05-28'], (1.56,.4,0,0))

    def test_fiscal_availability_and_all_file_consumers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'actions.csv'
            with path.open('w', newline='') as f:
                w=csv.DictWriter(f, fieldnames=ca.ACTION_FIELDS); w.writeheader(); w.writerows(self.rows * 2)
            dists = div.load_distributions(path)['300760']
            self.assertIsNone(div.annual_dividend(dists, '2026-03-27'))
            self.assertEqual(div.annual_dividend(dists, '2026-05-28'), (.31, '2025'))
            self.assertEqual(div.annual_dividend(dists, '2027-05-01'), (1.25, '2026'))
            with patch.object(bt, 'ACTIONS', path):
                self.assertEqual(bt.load_actions()['300760']['2026-05-28'], (1.56,0,0,0))
            with patch.object(bands, 'ACTIONS', path):
                self.assertEqual(len(bands.load_actions()['300760']), 2)
            self.assertEqual(event_from_actions(path, '300760', '2026-05-28')['cash'], 1.56)

    def test_booked_dividend_keeps_report_and_notice(self):
        # Annual plan is already an H1 payable; unimplemented current interim is uncertain.
        rows = [dict(r, ex_dividend_date='2026-09-01') for r in self.rows]
        certain, uncertain = bands.dividends_booked_since(rows, '2025-12-31', '2026-06-30', '2026-08-28')
        self.assertAlmostEqual(certain, .31)
        self.assertEqual(uncertain, [1.25])

    def test_verified_source_duplicate_excluded_but_amount_change_fails(self):
        row=raw('1997-06-30', 0, SECURITY_CODE='600080', PLAN_NOTICE_DATE='1997-08-14',
                EX_DIVIDEND_DATE='1997-08-19', IT_RATIO=6)
        self.assertEqual(ca.normalize_eastmoney([row]), [])
        with self.assertRaisesRegex(ValueError, 'Excluded source component changed'):
            ca.normalize_eastmoney([dict(row, IT_RATIO=7)])

    def test_code_succession_preserves_both_plans(self):
        rows=[dict(r, security_code='001872', ex_dividend_date='2016-06-01') for r in self.rows]
        expanded, added = code_succession.expand_actions(rows)
        self.assertEqual(added, 2)
        self.assertEqual(len([r for r in expanded if r['security_code']=='000022']), 2)
        self.assertEqual(code_succession.expand_actions(expanded)[1], 0)

    def test_succession_does_not_reclone_when_announcement_metadata_improves(self):
        old=component(security_code='000022',ex_dividend_date='2016-06-01',notice='')
        fresh=component(security_code='001872',ex_dividend_date='2016-06-01')
        out,added=code_succession.expand_actions([old,fresh])
        self.assertEqual(added,0); self.assertIn(old,out)
        with self.assertRaisesRegex(ValueError,'Conflicting legacy'):
            code_succession.expand_actions([old,dict(fresh,cash_per_share='.32')])
        with self.assertRaisesRegex(ValueError,'Ambiguous legacy'):
            code_succession.expand_actions([old,fresh,dict(fresh,plan_notice_date='2026-03-29')])

    def test_nonfinite_or_negative_amount_rejected(self):
        for amount in ('nan','inf','-.1'):
            with self.assertRaises(ValueError): ca.unique_actions([component(cash=amount)])

    def test_overseas_reverse_split_remains_supported(self):
        reverse=component(report='',notice='',cash='0',shares='-.875',security_code='0000040545')
        self.assertEqual(ca.event_map([reverse])['0000040545']['2026-05-28'],(0,-.875,0,0))
        for ratio in ('-1','-1.01'):
            with self.assertRaises(ValueError): ca.aggregate_actions([dict(reverse,share_ratio=ratio)])

class FetchTest(unittest.TestCase):
    def responses(self, count=2):
        return [io.BytesIO(json.dumps(dict(success=True,result=dict(count=count,pages=2,data=[r]))).encode())
                for r in [raw(),raw('2026-03-31',12.5)]]

    def test_paginated_daily_events(self):
        with patch('urllib.request.urlopen', side_effect=self.responses()) as request:
            events=fetch.fetch_ex_dividend_events('2026-05-28')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(events['300760']['cash_per_share'], 1.56)

    def test_paginated_company_components(self):
        with patch('urllib.request.urlopen', side_effect=self.responses()):
            events=history.fetch_actions('300760', 15)
        self.assertEqual(len(events), 2)
        self.assertEqual(ca.aggregate_actions(events)[0]['cash_per_share'],1.56)

    def test_incomplete_pages_fail(self):
        for call in (lambda: fetch.fetch_ex_dividend_events('2026-05-28'), lambda: history.fetch_actions('300760',15)):
            with patch('urllib.request.urlopen', side_effect=self.responses(3)), self.assertRaises(ValueError): call()

class ShadowTest(unittest.TestCase):
    def test_correction_keeps_original_input_and_future_boundary(self):
        from shadow_from_origin import corrected_actions
        old=[dict(date='2026-08-28', all_actions={'300760':{'2026-05-28':{'cash_per_share':.31}}},
                  actions={}, quotes={'300760':{'close':164.3}})]
        correction=dict(through='2026-09-21', known_by='2026-08-28',
                        events={'300760':{'2026-05-28':{'cash_per_share':1.56}}})
        new=corrected_actions(old, correction)
        self.assertEqual(old[0]['all_actions']['300760']['2026-05-28']['cash_per_share'],.31)
        self.assertEqual(new[0]['all_actions']['300760']['2026-05-28']['cash_per_share'],1.56)
        self.assertEqual(new[0]['quotes'],old[0]['quotes'])
        self.assertEqual(new[0]['actions'],{})
        with self.assertRaises(ValueError):
            corrected_actions(old,dict(correction,known_by='2026-05-01'))

if __name__=='__main__':
    unittest.main()
