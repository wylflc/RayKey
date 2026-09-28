#!/usr/bin/env python3
"""OI-178（§6.8）：SEC 标签按经济含义组合——合并税前利润不由境内单项兜底、有息负债分层只取一次、折旧＋无形资产摊销；
年报与 10-Q TTM 两条路径同规。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_overseas_statements as st  # noqa: E402


def getter(values: dict):
    return lambda key: values.get(key)


class PretaxCompositionTest(unittest.TestCase):
    def test_consolidated_tag_wins(self):
        v, parts = st.compose_sum(getter({"pretax": 100.0, "pretax_domestic": 30.0, "pretax_foreign": 70.0}), st.PRETAX_RULES)
        self.assertEqual((v, parts), (100.0, ("pretax",)))

    def test_domestic_plus_foreign_when_no_consolidated_tag(self):
        # 甲骨文 FY2026：境内 8.693b、境外 10.861b → 合并 19.554b（原实现取境内 8.693b）
        v, parts = st.compose_sum(getter({"pretax_domestic": 8.693, "pretax_foreign": 10.861}), st.PRETAX_RULES)
        self.assertAlmostEqual(v, 19.554); self.assertEqual(parts, ("pretax_domestic", "pretax_foreign"))

    def test_domestic_alone_never_used(self):
        v, parts = st.compose_sum(getter({"pretax_domestic": 8.693}), st.PRETAX_RULES)
        self.assertIsNone(v); self.assertEqual(parts, ())
        v, parts = st.compose_sum(getter({"pretax_domestic": 8.693, "profit_loss": 17.309, "income_tax": 2.467}), st.PRETAX_RULES)
        self.assertAlmostEqual(v, 19.776); self.assertEqual(parts, ("profit_loss", "income_tax"))

    def test_continuing_income_plus_tax_precedes_profit_loss(self):
        v, parts = st.compose_sum(getter({"continuing_income": 15.0, "profit_loss": 17.0, "income_tax": 2.0}), st.PRETAX_RULES)
        self.assertEqual((v, parts), (17.0, ("continuing_income", "income_tax")))


class DebtCompositionTest(unittest.TestCase):
    def test_oracle_notes_current_total_and_finance_leases(self):
        # FY2026 官方口径 137,242：非流动票据 122,342 + 流动债务合计 7,199（= NotesPayableCurrent，同一行两个标签）+ 融资租赁 7,081 + 620
        v, parts = st.compose_debt(getter({"lt_notes_noncurrent": 122342.0, "notes_current": 7199.0, "debt_current_total": 7199.0,
                                           "fin_lease_noncurrent": 7081.0, "fin_lease_current": 620.0, "fin_lease_total": 7701.0,
                                           "st_debt": 0.0}))
        self.assertAlmostEqual(v, 137242.0)
        self.assertEqual(parts, ("lt_notes_noncurrent", "debt_current_total", "fin_lease_noncurrent", "fin_lease_current"))

    def test_debt_current_total_is_not_stacked_on_current_maturities(self):
        # 非流动 90 + 流动合计 15（含一年内到期 10、商业票据 5）：不得再叠加 10 与 5
        v, _ = st.compose_debt(getter({"lt_debt_noncurrent": 90.0, "lt_debt_current": 10.0, "debt_current_total": 15.0, "st_debt": 5.0}))
        self.assertAlmostEqual(v, 105.0)

    def test_long_term_debt_alone_is_a_total_and_only_adds_short_term_borrowings(self):
        v, parts = st.compose_debt(getter({"lt_debt_total": 100.0, "st_debt": 2.0}))
        self.assertAlmostEqual(v, 102.0); self.assertEqual(parts, ("lt_debt_total", "st_debt"))

    def test_long_term_debt_with_a_current_line_is_the_noncurrent_line(self):
        # Adobe FY2024：LongTermDebt 4,129 为非流动行，LongTermDebtCurrent 1,500 ≈ DebtCurrent 1,499 → 5,628
        v, parts = st.compose_debt(getter({"lt_debt_total": 4129.0, "lt_debt_current": 1500.0, "debt_current_total": 1499.0}))
        self.assertAlmostEqual(v, 5628.0); self.assertEqual(parts, ("lt_debt_total", "debt_current_total"))
        # 特斯拉 2023：LongTermDebt 2,682 + DebtCurrent 1,975 + 融资租赁 175/398 = 5,230（报表「债务及融资租赁」两行之和）
        v, _ = st.compose_debt(getter({"lt_debt_total": 2682.0, "debt_current_total": 1975.0,
                                       "fin_lease_noncurrent": 175.0, "fin_lease_current": 398.0, "fin_lease_total": 573.0}))
        self.assertAlmostEqual(v, 5230.0)

    def test_including_current_maturities_total_minus_current_split(self):
        v, _ = st.compose_debt(getter({"ltd_lease_total": 100.0, "ltd_lease_current": 10.0}))
        self.assertAlmostEqual(v, 100.0)

    def test_lease_inclusive_noncurrent_treats_debt_current_as_lease_inclusive(self):
        # 美光 FY2025：LongTermDebtAndCapitalLeaseObligations 14,017（含租赁）+ 「Current debt」560（= 当期融资租赁）→ 14,577，不再加 560
        v, parts = st.compose_debt(getter({"ltd_lease_noncurrent": 14017.0, "debt_current_total": 560.0,
                                           "fin_lease_noncurrent": 2484.0, "fin_lease_current": 560.0, "fin_lease_total": 3044.0}))
        self.assertAlmostEqual(v, 14577.0); self.assertEqual(parts, ("ltd_lease_noncurrent", "debt_current_total"))

    def test_short_term_tag_equal_to_current_maturities_counts_once(self):
        # AMD 2023：「Short-term debt」751 同时打 LongTermDebtCurrent 与 ShortTermBorrowings
        v, parts = st.compose_debt(getter({"lt_debt_noncurrent": 1717.0, "lt_debt_current": 751.0, "st_debt": 751.0}))
        self.assertAlmostEqual(v, 2468.0); self.assertEqual(parts, ("lt_debt_noncurrent", "lt_debt_current"))

    def test_lease_inclusive_tags_do_not_double_count_leases(self):
        v, parts = st.compose_debt(getter({"ltd_lease_noncurrent": 80.0, "ltd_lease_current": 5.0,
                                           "fin_lease_noncurrent": 3.0, "fin_lease_current": 1.0, "fin_lease_total": 4.0}))
        self.assertAlmostEqual(v, 85.0); self.assertEqual(parts, ("ltd_lease_noncurrent", "ltd_lease_current"))

    def test_finance_lease_total_fallback_and_no_lease(self):
        v, parts = st.compose_debt(getter({"lt_debt_noncurrent": 50.0, "lt_debt_current": 5.0, "fin_lease_total": 4.0}))
        self.assertAlmostEqual(v, 59.0); self.assertIn("fin_lease_total", parts)
        v, parts = st.compose_debt(getter({"lt_debt_noncurrent": 50.0, "st_debt": 5.0}))
        self.assertAlmostEqual(v, 55.0); self.assertEqual(parts, ("lt_debt_noncurrent", "st_debt"))

    def test_nothing_tagged_is_zero_debt(self):
        self.assertEqual(st.compose_debt(getter({})), (0.0, ()))


class DepAmortCompositionTest(unittest.TestCase):
    def test_combined_tag_precedes_components(self):
        v, parts = st.compose_sum(getter({"dep_amort": 10.0, "depreciation": 7.0, "amort_intangible": 2.0}), st.DEP_AMORT_RULES)
        self.assertEqual((v, parts), (10.0, ("dep_amort",)))

    def test_depreciation_plus_intangible_amortization(self):
        # 甲骨文 FY2026：折旧 7,623 + 无形资产摊销 1,671 = 9,294（原实现只取折旧）
        v, parts = st.compose_sum(getter({"depreciation": 7623.0, "amort_intangible": 1671.0}), st.DEP_AMORT_RULES)
        self.assertAlmostEqual(v, 9294.0); self.assertEqual(parts, ("depreciation", "amort_intangible"))

    def test_depreciation_alone_is_last_resort_and_tagged(self):
        v, parts = st.compose_sum(getter({"depreciation": 7623.0}), st.DEP_AMORT_RULES)
        self.assertEqual((v, parts), (7623.0, ("depreciation",)))
        tags = st._composed_tags({"depreciation": "Depreciation"}, {"dep_amort": parts})
        self.assertEqual(tags["dep_amort"], "Depreciation")


def facts_fixture():
    """甲骨文形态的最小 companyfacts：年报只有境内／境外税前、票据与融资租赁拆分、折旧与摊销拆分；10-Q 同形态。"""
    g = st.GAAP
    facts = {}

    def duration(key, annual, current, previous):
        facts[g[key][0]] = {"units": {"shares" if key == "shares" else "USD": [
            dict(start="2025-06-01", end="2026-05-31", filed="2026-06-22", fp="FY", form="10-K", val=annual),
            dict(start="2026-06-01", end="2026-08-31", filed="2026-09-11", fp="Q1", form="10-Q", val=current),
            dict(start="2025-06-01", end="2025-08-31", filed="2026-09-11", fp="Q1", form="10-Q", val=previous),
        ]}}

    def instant(key, annual, current, concept=None):
        facts[concept or g[key][0]] = {"units": {"USD": [
            dict(end="2026-05-31", filed="2026-06-22", fp="FY", form="10-K", val=annual),
            dict(end="2026-08-31", filed="2026-09-11", fp="Q1", form="10-Q", val=current),
        ]}}

    duration("revenue", 67357.0, 19345.0, 14926.0)
    duration("operating_income", 20606.0, 6000.0, 3549.0)
    duration("pretax_domestic", 8693.0, 3000.0, 1500.0)
    duration("pretax_foreign", 10861.0, 3500.0, 2820.0)
    duration("income_tax", 2467.0, 800.0, 453.0)
    duration("depreciation", 7623.0, 2600.0, 1400.0)
    duration("amort_intangible", 1671.0, 400.0, 500.0)
    duration("shares", 2914.0, 3000.0, 2909.0)
    instant("total_equity", 43056.0, 67196.0)
    instant("parent_equity", 42508.0, 66600.0)
    instant("lt_notes_noncurrent", 122342.0, 118000.0)
    instant("notes_current", 7199.0, 7337.0)
    instant("debt_current_total", 7199.0, 7337.0)
    instant("fin_lease_noncurrent", 7081.0, 7500.0)
    instant("fin_lease_current", 620.0, 700.0)
    instant("fin_lease_total", 7701.0, 8200.0)
    return {"facts": {"us-gaap": facts}}


class SecPathsTest(unittest.TestCase):
    def test_annual_and_ttm_paths_compose_consistently(self):
        data = facts_fixture()
        rows = st.sec_extract("ORCL", "甲骨文", data)
        annual = [r for r in rows if r["period"] == "2026-05-31"][0]
        self.assertAlmostEqual(annual["pretax"], 19554.0)
        self.assertAlmostEqual(annual["interest_debt"], 137242.0)
        self.assertAlmostEqual(annual["dep_amort"], 9294.0)
        self.assertIn("pretax=IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic+IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign",
                      annual["tags_used"])
        self.assertIn("interest_debt=LongTermNotesPayable+DebtCurrent+FinanceLeaseLiabilityNoncurrent+FinanceLeaseLiabilityCurrent", annual["tags_used"])
        self.assertIn("dep_amort=Depreciation+AmortizationOfIntangibleAssets", annual["tags_used"])
        current = st.sec_current_extract("ORCL", "甲骨文", data["facts"]["us-gaap"], st.GAAP, rows, "2026-09-11")
        self.assertIsNotNone(current)
        self.assertAlmostEqual(current["pretax"], 19554.0 + (3000.0 + 3500.0) - (1500.0 + 2820.0))
        self.assertAlmostEqual(current["interest_debt"], 118000.0 + 7337.0 + 7500.0 + 700.0)
        self.assertAlmostEqual(current["dep_amort"], 9294.0 + (2600.0 + 400.0) - (1400.0 + 500.0))
        self.assertIn("interest_debt=LongTermNotesPayable+DebtCurrent+FinanceLeaseLiabilityNoncurrent+FinanceLeaseLiabilityCurrent", current["tags_used"])

    def test_domestic_only_filer_has_no_pretax_and_falls_back_to_operating_income(self):
        data = facts_fixture()
        del data["facts"]["us-gaap"][st.GAAP["pretax_foreign"][0]]
        rows = st.sec_extract("X", "x", data)
        annual = [r for r in rows if r["period"] == "2026-05-31"][0]
        self.assertIsNone(annual["pretax"])                     # 不以境内 8,693 冒充合并税前
        self.assertAlmostEqual(annual["ebit"], annual["operating_income"])
        self.assertNotIn("pretax=", annual["tags_used"])


def fy(end: str, filed: str, val: float, accn: str, duration: bool = False, form: str = "10-K") -> dict:
    entry = dict(end=end, filed=filed, fp="FY", form=form, val=val, accn=accn)
    if duration:
        entry["start"] = f"{int(end[:4])}-01-01"
    return entry


class SecCurrencyFrameworkTest(unittest.TestCase):
    """OI-228（§6.8）：每份申报只取其报表币的条目；币种与准则切换逐期取最新年报。"""

    def test_stray_foreign_currency_entry_is_ignored(self):
        # SLB：LongTermDebtNoncurrent 在同一份 10-K 里有一条 EUR（且排在前面），原实现只取第一个币种
        pretax = st.GAAP["pretax"][0]
        data = {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [fy("2024-12-31", "2025-02-01", 1000.0, "a1", True)]}},
            pretax: {"units": {"USD": [fy("2024-12-31", "2025-02-01", 100.0, "a1", True)]}},
            "StockholdersEquity": {"units": {"USD": [fy("2024-12-31", "2025-02-01", 500.0, "a1")]}},
            "LongTermDebtNoncurrent": {"units": {"EUR": [fy("2024-12-31", "2025-02-01", 7.0, "a1")],
                                                 "USD": [fy("2024-12-31", "2025-02-01", 300.0, "a1")]}}}}}
        row = st.sec_extract("SLB", "x", data)[-1]
        self.assertEqual(row["report_currency"], "USD")
        self.assertAlmostEqual(row["interest_debt"], 300.0)

    def test_convenience_translation_is_ignored(self):
        # 境外发行人 20-F 的美元便利折算只覆盖最新一年，条目少于报表币
        data = {"facts": {"ifrs-full": {
            "Revenue": {"units": {"USD": [fy("2024-12-31", "2025-04-10", 100.0, "t24", True, "20-F")],
                                  "TWD": [fy("2024-12-31", "2025-04-10", 3000.0, "t24", True, "20-F"),
                                          fy("2023-12-31", "2025-04-10", 2500.0, "t24", True, "20-F")]}},
            "ProfitLossBeforeTax": {"units": {"USD": [fy("2024-12-31", "2025-04-10", 40.0, "t24", True, "20-F")],
                                              "TWD": [fy("2024-12-31", "2025-04-10", 1200.0, "t24", True, "20-F"),
                                                      fy("2023-12-31", "2025-04-10", 1000.0, "t24", True, "20-F")]}},
            "Equity": {"units": {"TWD": [fy("2024-12-31", "2025-04-10", 5000.0, "t24", form="20-F")]}}}}}
        rows = st.sec_extract("TSMX", "x", data)
        self.assertEqual([r["report_currency"] for r in rows], ["TWD", "TWD"])
        self.assertAlmostEqual(rows[-1]["revenue"], 3000.0)

    def crh(self) -> dict:
        """20-F 欧元（FY2019）→ 20-F 美元（FY2020 起，重述两年比较数）→ 10-K us-gaap（FY2023 起，重述 FY2021–2022 损益）。"""
        ifrs = {
            "Revenue": {"units": {
                "EUR": [fy("2018-12-31", "2020-03-06", 26000.0, "e19", True, "20-F"), fy("2019-12-31", "2020-03-06", 27000.0, "e19", True, "20-F")],
                "USD": [fy("2018-12-31", "2021-03-12", 30000.0, "u20", True, "20-F"), fy("2019-12-31", "2021-03-12", 31000.0, "u20", True, "20-F"),
                        fy("2020-12-31", "2021-03-12", 31500.0, "u20", True, "20-F"),
                        fy("2021-12-31", "2023-03-10", 32000.0, "u22", True, "20-F"), fy("2022-12-31", "2023-03-10", 34000.0, "u22", True, "20-F")]}},
            "ProfitLossBeforeTax": {"units": {
                "EUR": [fy("2018-12-31", "2020-03-06", 2000.0, "e19", True, "20-F"), fy("2019-12-31", "2020-03-06", 2200.0, "e19", True, "20-F")],
                "USD": [fy("2019-12-31", "2021-03-12", 2500.0, "u20", True, "20-F"), fy("2020-12-31", "2021-03-12", 2400.0, "u20", True, "20-F"),
                        fy("2021-12-31", "2023-03-10", 2900.0, "u22", True, "20-F"), fy("2022-12-31", "2023-03-10", 3000.0, "u22", True, "20-F")]}},
            "Equity": {"units": {
                "EUR": [fy("2019-12-31", "2020-03-06", 16000.0, "e19", form="20-F")],
                "USD": [fy("2020-12-31", "2021-03-12", 19000.0, "u20", form="20-F"),
                        fy("2021-12-31", "2023-03-10", 21000.0, "u22", form="20-F"), fy("2022-12-31", "2023-03-10", 22000.0, "u22", form="20-F")]}},
            "Assets": {"units": {
                "EUR": [fy("2019-12-31", "2020-03-06", 40000.0, "e19", form="20-F")],
                "USD": [fy("2020-12-31", "2021-03-12", 45000.0, "u20", form="20-F"),
                        fy("2021-12-31", "2023-03-10", 47000.0, "u22", form="20-F"), fy("2022-12-31", "2023-03-10", 48000.0, "u22", form="20-F")]}}}
        pretax = st.GAAP["pretax"][0]
        us = {
            st.GAAP["revenue"][0]: {"units": {"USD": [fy("2021-12-31", "2024-02-29", 31900.0, "g23", True), fy("2022-12-31", "2024-02-29", 33900.0, "g23", True),
                                                      fy("2023-12-31", "2024-02-29", 35000.0, "g23", True)]}},
            pretax: {"units": {"USD": [fy("2021-12-31", "2024-02-29", 2800.0, "g23", True), fy("2022-12-31", "2024-02-29", 3100.0, "g23", True),
                                       fy("2023-12-31", "2024-02-29", 3500.0, "g23", True)]}},
            "StockholdersEquity": {"units": {"USD": [fy("2022-12-31", "2024-02-29", 22500.0, "g23"), fy("2023-12-31", "2024-02-29", 24000.0, "g23")]}},
            # 权益变动表的期初余额把权益带到 FY2021 期末，资产负债表（总资产）只列两年
            st.GAAP["total_equity"][0]: {"units": {"USD": [fy("2021-12-31", "2024-02-29", 21500.0, "g23"), fy("2022-12-31", "2024-02-29", 22800.0, "g23"),
                                                           fy("2023-12-31", "2024-02-29", 24300.0, "g23")]}},
            "Assets": {"units": {"USD": [fy("2022-12-31", "2024-02-29", 48500.0, "g23"), fy("2023-12-31", "2024-02-29", 50000.0, "g23")]}}}
        return {"ifrs-full": ifrs, "us-gaap": us}

    def test_currency_switch_uses_restated_comparatives_and_drops_older_currency(self):
        facts = self.crh()
        before = {"ifrs-full": {c: {"units": {u: [e for e in es if e["filed"] <= "2020-12-31"] for u, es in n["units"].items()
                                              if any(e["filed"] <= "2020-12-31" for e in es)}}
                                for c, n in facts["ifrs-full"].items()}}
        rows = st.sec_extract("CRH", "x", {"facts": before})
        self.assertEqual([(r["period"], r["report_currency"], r["revenue"]) for r in rows],
                         [("2018-12-31", "EUR", 26000.0), ("2019-12-31", "EUR", 27000.0)])
        only_ifrs = {"ifrs-full": facts["ifrs-full"]}
        rows = st.sec_extract("CRH", "x", {"facts": only_ifrs})
        self.assertEqual({r["report_currency"] for r in rows}, {"USD"})            # 欧元年报被美元重述比较数取代
        self.assertAlmostEqual([r for r in rows if r["period"] == "2019-12-31"][0]["revenue"], 31000.0)

    def test_framework_switch_takes_latest_balance_sheet_filing_per_period(self):
        facts = self.crh()
        self.assertEqual(st.sec_frameworks(facts), ["ifrs-full", "us-gaap"])
        self.assertEqual(st.current_framework(facts), "us-gaap")
        rows = {r["period"]: r for r in st.sec_extract("CRH", "x", {"facts": facts})}
        self.assertEqual(rows["2021-12-31"]["source"], "SEC companyfacts ifrs-full")   # us-gaap 该期末只有权益变动表的期初余额
        self.assertAlmostEqual(rows["2021-12-31"]["revenue"], 32000.0)
        self.assertEqual(rows["2022-12-31"]["source"], "SEC companyfacts us-gaap")     # 10-K 晚于 20-F 报告该期末总资产
        self.assertAlmostEqual(rows["2022-12-31"]["revenue"], 33900.0)
        self.assertEqual(rows["2023-12-31"]["source"], "SEC companyfacts us-gaap")
        self.assertEqual({r["report_currency"] for r in rows.values()}, {"USD"})


if __name__ == "__main__":
    unittest.main()
