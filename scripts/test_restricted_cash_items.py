#!/usr/bin/env python3
"""OI-219 受限资产附注解析与质押开票现金类扣减的单元测试（无网络）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_restricted_cash_items as rc  # noqa: E402
import roic_inputs  # noqa: E402


class ParseSectionTest(unittest.TestCase):
    def test_one_period_table_with_reasons(self):
        body = ("\n单位：元 币种：人民币\n项目 期末账面价值 受限原因\n"
                "货币资金 1,096,591,549.00 质押开具银行承兑汇票 注1\n其他非流动资产 3,230,000,000.00 质押开具银行承兑汇票 注2\n"
                "固定资产 200,000,000.00 抵押借款\n合计 4,526,591,549.00 /\n其他说明：\n注1：银行承兑票据保证金。\n")
        r = rc.parse_section(body)
        self.assertEqual(r["status"], "ok")
        self.assertEqual([x["label"] for x in r["rows"]], ["货币资金", "其他非流动资产", "固定资产"])
        self.assertIn("承兑汇票", r["rows"][0]["reason"])

    def test_two_period_table_footnote_and_opening_only_row(self):
        # 新版式：每期「账面余额 账面价值 类型 情况」，原因只写「质押 注 N」；固定资产行只有期初数
        body = ("\n单位：元 币种：人民币\n项目\n期末 期初\n账面余额 账面价值 受限\n类型\n受限\n情况 账面余额 账面价值 受限\n类型\n受限\n情况\n"
                "货币资\n金\n473,334,44\n8.37\n473,334,\n448.37 质押 注 1 1,099,964\n,455.37\n1,099,964,\n455.37 质押 注 1\n"
                "其他非\n流动资\n产\n4,100,000,\n000.00\n4,100,00\n0,000.00 质押 注 2 4,101,970\n,833.33\n4,101,970,\n833.33 质押 注 2\n"
                "固定资\n产\n56,944,50\n2.69\n56,944,502\n.69 抵押 注 3\n"
                "合计 4,573,334,\n448.37\n4,573,33\n4,448.37 / / 5,258,879\n,791.39\n5,258,879,\n791.39 / /\n其他说明：\n"
                "注 1：以银行承兑票据保证金为质押开具银行承兑汇票。\n注 2：以三年期定期存单为质押开具银行承兑汇票。\n注 3：借款抵押。\n")
        r = rc.parse_section(body)
        self.assertEqual(r["status"], "ok")
        self.assertEqual([x["label"] for x in r["rows"]], ["货币资金", "其他非流动资产"])
        self.assertAlmostEqual(r["rows"][1]["value"], 4_100_000_000.00, places=2)
        self.assertIn("承兑汇票", r["rows"][1]["reason"])

    def test_cash_note_breakdown_table(self):
        body = "\n项  目 期末余额 年初余额\n银行承兑汇票保证金 27,314,056.04 9,317,741.07\n定期存款 2,040,865.04\n合 计 29,354,921.08 9,317,741.07\n"
        r = rc.parse_section(body, cash_note=True)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["rows"]), 2)
        self.assertIn("承兑汇票", r["rows"][0]["reason"])


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.task = dict(code="000001", year=2025, balance={"MONETARYFUNDS": 1_000.0})

    def test_categories_and_caps(self):
        rows = [dict(label="货币资金", value=800.0, reason="银行承兑汇票保证金、借款质押"),
                dict(label="其他非流动资产", value=500.0, reason="质押开具银行承兑汇票"),
                dict(label="一年内到期的非流动资产", value=300.0, reason="质押"),
                dict(label="交易性金融资产", value=100.0, reason="借款质押"),
                dict(label="固定资产", value=900.0, reason="开具保函抵押")]
        note_cash = {("000001", 2025, "OTHER_NONCURRENT_ASSET"): 400.0,
                     ("000001", 2025, "NONCURRENT_ASSET_1YEAR"): 300.0}
        c = rc.classify(rows, self.task, note_cash)
        self.assertAlmostEqual(c["counted"], 800.0 + 400.0)      # 混写借款整行计入；附注行以核定现金为限
        self.assertAlmostEqual(c["generic"], 300.0)
        self.assertAlmostEqual(c["loan"], 100.0)                 # 交易性金融资产无报表行值时不设限


class EngineDeductionTest(unittest.TestCase):
    @staticmethod
    def parts(notes_payable: float) -> dict:
        bal = dict(TOTAL_EQUITY="1000", TOTAL_PARENT_EQUITY="1000", MONETARYFUNDS="900", NOTE_PAYABLE=str(notes_payable),
                   TOTAL_ASSETS="3000", NOTICE_DATE="2026-04-20")
        inc = dict(TOTAL_OPERATE_INCOME="1000", TOTAL_PROFIT="100", INCOME_TAX="25", FINANCE_EXPENSE="-20",
                   FE_INTEREST_INCOME="18", NOTICE_DATE="2026-04-20")
        return dict(balance=bal, income=inc)

    def test_deduction_capped_by_notes_payable_and_interest_added(self):
        base = roic_inputs._year_from_parts("000001", "2025-12-31", self.parts(300), False, 0.1, "nonop", 0.0)
        cut = roic_inputs._year_from_parts("000001", "2025-12-31", self.parts(300), False, 0.1, "nonop", 0.0, 500.0)
        self.assertAlmostEqual(cut.restricted_cash, 300.0)
        self.assertAlmostEqual(base.excess_cash - cut.excess_cash, 300.0)
        self.assertAlmostEqual(cut.restricted_interest, 300.0 * 18 / 900)
        self.assertAlmostEqual(cut.ebit - base.ebit, 6.0)

    def test_no_notes_payable_no_deduction(self):
        cut = roic_inputs._year_from_parts("000001", "2025-12-31", self.parts(0), False, 0.1, "nonop", 0.0, 500.0)
        self.assertEqual(cut.restricted_cash, 0.0)


if __name__ == "__main__":
    unittest.main()
