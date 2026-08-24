#!/usr/bin/env python3
"""股利折现分子（`divspread_dividend`）与银行名称判定的回归测试（OI-099）。

Run: ``python3 scripts/test_divspread_dividend.py``

锁定：①两笔年度分红相隔不足 365 天不再翻倍/腰斩；②中期＋年度按财年合计，不把「拆分」当「加倍」；
③自预案公告日起计入，不等除权；④财年在年度分配已知或过次年 4-30 后才算完整；⑤无 `plan_notice_date`
的旧行退到除权日；⑥非银行的「×行」名称不进股利折现名单。序列取自东财真实记录（工商银行、招商银行）。
"""
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import divspread_dividend as dd  # noqa: E402
from divspread_names import is_bank_name, is_divspread_financial  # noqa: E402


def dist(plan: str, report: str, cash: float, ex: str = "") -> dd.Distribution:
    return dd.Distribution(plan, report, cash, ex)


# 工商银行：FY2022 年度 0.3035（预案 2023-03-30，除权 2023-07-17）；FY2023 年度 0.3064（预案 2024-03-27，除权 2024-07-16）；
# FY2024 中期 0.1434（预案 2024-08-31，除权 2025-01-07）＋年度 0.1646（预案 2025-03-29，除权 2025-07-14）；
# FY2025 中期 0.1414（预案 2025-08-30）＋年度 0.1689（预案 2026-03-28，除权 2026-05-13）。
ICBC = [
    dist("2023-03-30", "2022-12-31", 0.3035, "2023-07-17"),
    dist("2024-03-27", "2023-12-31", 0.3064, "2024-07-16"),
    dist("2024-08-31", "2024-06-30", 0.1434, "2025-01-07"),
    dist("2025-03-29", "2024-12-31", 0.1646, "2025-07-14"),
    dist("2025-08-30", "2025-06-30", 0.1414, "2025-12-15"),
    dist("2026-03-28", "2025-12-31", 0.1689, "2026-05-13"),
]


class AnnualDividendTest(unittest.TestCase):
    def test_no_doubling_when_two_annual_ex_dates_within_365_days(self):
        # 旧口径：2024-07-16 当天窗口同时含 2023-07-17 与 2024-07-16 两笔 → 0.6099；次日退回 0.3064
        for day in ("2024-07-15", "2024-07-16", "2024-07-17", "2024-08-30"):
            self.assertEqual(dd.annual_dividend(ICBC, day), (0.3064, "2023"), day)

    def test_interim_plus_annual_sum_by_fiscal_year_not_ttm(self):
        # FY2024 中期预案（2024-08-31）后财年尚未完整 → 仍用 FY2023；年度预案（2025-03-29）当天起 FY2024 = 0.1434 + 0.1646
        self.assertEqual(dd.annual_dividend(ICBC, "2024-08-31"), (0.3064, "2023"))
        self.assertEqual(dd.annual_dividend(ICBC, "2025-03-28"), (0.3064, "2023"))
        total, fy = dd.annual_dividend(ICBC, "2025-03-29")
        self.assertEqual(fy, "2024")
        self.assertAlmostEqual(total, 0.3080, places=6)
        # 旧口径在 2025-07-14 会得 0.1434 + 0.1646 + 0.3064（三笔同窗）——新口径整段平稳
        for day in ("2025-07-13", "2025-07-14", "2025-07-15", "2025-12-15", "2026-03-27"):
            self.assertAlmostEqual(dd.annual_dividend(ICBC, day)[0], 0.3080, places=6, msg=day)
        total, fy = dd.annual_dividend(ICBC, "2026-03-28")
        self.assertEqual((round(total, 6), fy), (0.3103, "2025"))

    def test_effective_from_plan_notice_not_ex_date(self):
        # FY2023 年度预案 2024-03-27 → 当天即用 0.3064，不等 2024-07-16 除权
        self.assertEqual(dd.annual_dividend(ICBC, "2024-03-26"), (0.3035, "2022"))
        self.assertEqual(dd.annual_dividend(ICBC, "2024-03-27"), (0.3064, "2023"))

    def test_fiscal_year_closes_by_deadline_when_no_annual_distribution(self):
        # 只派中期、年报后不分红：过 4-30 后 FY 完整，合计 = 中期
        d = [dist("2024-03-20", "2023-12-31", 1.0, "2024-06-20"),
             dist("2024-08-20", "2024-06-30", 0.4, "2024-10-10")]
        self.assertEqual(dd.annual_dividend(d, "2025-04-30"), (1.0, "2023"))
        self.assertEqual(dd.annual_dividend(d, "2025-05-01"), (0.4, "2024"))
        # 之后一年什么都没派：FY2025 过期合计 0 → 无值，不退到更早财年
        self.assertIsNone(dd.annual_dividend(d, "2026-05-01"))

    def test_nothing_known_or_before_first_plan(self):
        self.assertIsNone(dd.annual_dividend([], "2024-01-01"))
        self.assertIsNone(dd.annual_dividend(ICBC, "2023-03-29"))

    def test_deadline_helper(self):
        self.assertEqual(dd.fiscal_year_closed_by_deadline("2026-04-30"), 2024)
        self.assertEqual(dd.fiscal_year_closed_by_deadline("2026-05-01"), 2025)
        self.assertEqual(dd.fiscal_year_closed_by_deadline("2026-12-31"), 2025)

    def test_dividend_value(self):
        self.assertAlmostEqual(dd.dividend_value(0.3064, 0.0168), 0.3064 / 0.0368)
        self.assertIsNone(dd.dividend_value(0.3, -0.05, 0.02))


class LoadDistributionsTest(unittest.TestCase):
    def test_plan_date_preferred_and_pending_rows_kept_and_legacy_rows_fall_back(self):
        fields = ["security_code", "security_name", "ex_dividend_date", "cash_per_share", "share_ratio",
                  "plan", "report_date", "plan_notice_date", "progress"]
        rows = [
            {"security_code": "601398", "ex_dividend_date": "2024-07-16", "cash_per_share": "0.3064",
             "share_ratio": "0", "report_date": "2023-12-31", "plan_notice_date": "2024-03-27"},
            {"security_code": "601398", "ex_dividend_date": "", "cash_per_share": "0.15",
             "share_ratio": "0", "report_date": "2026-06-30", "plan_notice_date": "2026-08-29", "progress": "董事会决议通过"},
            {"security_code": "601398", "ex_dividend_date": "2023-07-17", "cash_per_share": "0.3035",
             "share_ratio": "0", "report_date": "2022-12-31", "plan_notice_date": ""},          # 旧行：退到除权日
            {"security_code": "601398", "ex_dividend_date": "2020-06-01", "cash_per_share": "0",
             "share_ratio": "0.5", "report_date": "2019-12-31", "plan_notice_date": "2020-03-01"},  # 纯送转：不计
            {"security_code": "600036", "ex_dividend_date": "2024-07-11", "cash_per_share": "1.972",
             "share_ratio": "0", "report_date": "2023-12-31", "plan_notice_date": "2024-03-25"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "actions.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields, restval="")
                writer.writeheader()
                writer.writerows(rows)
            got = dd.load_distributions(path, codes={"601398"})
        self.assertEqual(set(got), {"601398"})
        self.assertEqual([(d.available_at, d.report_date, d.cash) for d in got["601398"]],
                         [("2023-07-17", "2022-12-31", 0.3035), ("2024-03-27", "2023-12-31", 0.3064),
                          ("2026-08-29", "2026-06-30", 0.15)])
        self.assertEqual(got["601398"][2].ex_date, "")


class BankNameTest(unittest.TestCase):
    def test_banks_recognised(self):
        for name in ("工商银行", "张家港行", "青农商行", "渝农商行", "沪农商行", "苏农银行", "平安银行"):
            self.assertTrue(is_bank_name(name), name)

    def test_non_banks_ending_with_hang_excluded(self):
        for name in ("世联行", "任子行", "华致酒行", "喜悦智行", "永安行", "三人行", "兴业银锡"):
            self.assertFalse(is_bank_name(name), name)
            self.assertFalse(is_divspread_financial("000000", name), name)

    def test_insurers_by_code(self):
        self.assertTrue(is_divspread_financial("601318", "中国平安"))
        self.assertFalse(is_divspread_financial("001359", "平安电工"))


if __name__ == "__main__":
    unittest.main()
