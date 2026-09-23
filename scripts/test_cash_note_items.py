#!/usr/bin/env python3
"""OI-201 附注现金类解析与 OI-203 重述公告检测的单元测试（无网络）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_cash_note_items as notes  # noqa: E402
import scan_restatement_announcements as scan  # noqa: E402


class ParseSectionTest(unittest.TestCase):
    def test_decimal_table_counts_deposits_only(self):
        body = ("\n√适用 □不适用\n单位：元 币种：人民币\n项目 期末余额 期初余额\n合同取得成本\n"
                "定期存款及应收收益 4,066,666,099.49 3,090,912,300.73\n所得税预缴税款 3,329,974.70 3,615,829.56\n"
                "增值税留抵扣额 4,566,989.24 5,763,433.35\n其他 66,774,449.71 50,434,500.72\n"
                "合计 4,141,337,513.14 3,150,726,064.36\n其他说明\n")
        r = notes.parse_section(body, 4_141_337_513.14)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 4_066_666_099.49, places=2)

    def test_split_long_numbers_and_three_columns(self):
        body = ("\n单位：元 币种：人民币\n项目\n期末余额 期初余额\n账面余额 减值准 备 账面价值 账面余额 减值 准备 账面价值\n"
                "三年定期存单 4,386,109,7\n38.06\n4,386,109,7\n38.06\n5,042,003,55\n3.26\n5,042,003,\n553.26\n"
                "店面装修 159,503,194\n.02\n159,503,194\n.02\n226,149,857.\n36\n226,149,85\n7.36\n"
                "预付土地设备 工程款 101,098,724\n.05\n101,098,724\n.05\n251,223,222.\n38\n251,223,22\n2.38\n"
                "合计 4,646,711,6\n56.13\n4,646,711,6\n56.13\n5,519,376,63\n3.00\n5,519,376,\n633.00\n其他说明：\n")
        r = notes.parse_section(body, 4_646_711_656.13)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 4_386_109_738.06, places=2)

    def test_thousand_yuan_integer_table(self):
        body = ("\n单位：千元\n项目\n期末余额 期初余额\n账面余额 减值准备 账面价值 账面余额 减值准备 账面价值\n"
                "预付工程、设\n备款 12,192,925 29,944 12,162,981 8,504,151  8,504,151\n"
                "长期应收款项 125,106  125,106 127,947  127,947\n定期存单 2,018,582  2,018,582\n"
                "合计 14,336,613 29,944 14,306,669 8,632,098  8,632,098\n25、所有权或使用权受到限制的资产\n")
        r = notes.parse_section(body, 14_306_669_000.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 2_018_582_000.0)

    def test_blank_current_cell_is_not_read_as_current(self):
        body = ("\n单位：元\n项目 期末余额 期初余额\n预付长期资产款项 1,141,824,950.23 3,270,484,549.62\n"
                "持有至到期大额存单 212,310,138.91 1,333,961,164.38\n水电站特许使用权资产 580,115,756.20\n"
                "合计 1,354,135,089.14 5,184,561,470.20\n其他说明：\n")
        r = notes.parse_section(body, 1_354_135_089.14)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 212_310_138.91, places=2)

    def test_sub_rows_do_not_hide_parent_deposit(self):
        body = ("\n单位：元\n项目 期末余额 期初余额\n结构性存款 2,000,000,000.00 0.00\n其中：本金 1,990,000,000.00 0.00\n"
                "利息 10,000,000.00 0.00\n待抵扣进项税 500,000,000.00 400,000,000.00\n合计 2,500,000,000.00 400,000,000.00\n说明\n")
        r = notes.parse_section(body, 2_500_000_000.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 2_000_000_000.0)

    def test_pledged_deposit_counts_and_loans_do_not(self):
        body = ("\n单位：元\n项目 期末余额 期初余额\n质押定期存款及利息 300,000,000.00 0.00\n发放贷款及垫款 200,000,000.00 0.00\n"
                "应收保理款 100,000,000.00 0.00\n支付业务备付金 50,000,000.00 0.00\n合计 650,000,000.00 0.00\n说明\n")
        r = notes.parse_section(body, 650_000_000.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 300_000_000.0)

    def test_unlabeled_total_line(self):
        body = ("\n\n  2020年 12月 31日  2019年 12 月 31日\n\n 待抵扣增值税额 227,459,185  272,740,541\n"
                " 银行理财产品 300,000,000  250,000,000\n  527,459,185  522,740,541\n\n(9) 长期股权投资\n")
        r = notes.parse_section(body, 527_459_185.0)
        self.assertEqual(r["status"], "ok")
        self.assertAlmostEqual(r["cash"], 300_000_000.0)

    def test_wrong_table_is_rejected(self):
        body = "\n单位：元\n项目 期末余额\n理财产品 100.00\n合计 100.00\n"
        self.assertEqual(notes.parse_section(body, 5_000_000_000.0)["status"], "total_mismatch")


class RestatementScanTest(unittest.TestCase):
    def test_classify_titles(self):
        self.assertEqual(scan.classify("2025年第一季度报告（更新后）"), ("updated_report", "2025-03-31"))
        self.assertEqual(scan.classify("2014年年度报告（修订版）"), ("updated_report", "2014-12-31"))
        self.assertIsNone(scan.classify("2025年半年度报告摘要（更新后）"))
        self.assertEqual(scan.classify("关于前期会计差错更正的公告"), ("correction", ""))
        self.assertIsNone(scan.classify("2025年年度报告"))

    def test_pairing_window(self):
        rows = [dict(security_code="000858", kind="correction", announcement_date="2026-04-30", report_period=""),
                dict(security_code="000858", kind="updated_report", announcement_date="2026-04-30", report_period="2025-03-31"),
                dict(security_code="000858", kind="updated_report", announcement_date="2025-01-10", report_period="2024-09-30"),
                dict(security_code="002371", kind="correction", announcement_date="2026-04-18", report_period="")]
        scan.pair(rows)
        self.assertEqual([r["paired"] for r in rows], ["1", "1", "0", "0"])


if __name__ == "__main__":
    unittest.main()
