#!/usr/bin/env python3
"""§6.8 海外估值与 A 股生产口径统一（OI-210）的回归测试。

Run: ``python3 scripts/test_overseas_caliber.py``

锁住：标签组取最大（正表合计 ≥ 附注子项）与非流动项目的划分；EBIT 取经营利润、分部经营利润合计被识别并退回；
港股 EBIT 剔除其他收益、保留联营合营份额；超额现金、金融负债与投入资本下限；维护行沿用最近年报；
类金融判无法估值；估值参数不随质量档变化。
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_overseas_roic_bands as bands  # noqa: E402
import fetch_overseas_statements as statements  # noqa: E402
import roic_inputs  # noqa: E402


class FinancialAssetsTest(unittest.TestCase):
    def test_us_gaap_groups(self):
        values = {"CashAndCashEquivalentsAtCarryingValue": 100.0,
                  "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents": 130.0,     # 含受限现金，取大
                  "MarketableSecuritiesCurrent": 60.0, "ShortTermInvestments": 300.0,          # 正表合计 300 ≥ 附注子项 60
                  "HeldToMaturitySecuritiesNoncurrent": 70.0,
                  "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount": 20.0,
                  "LongTermInvestments": 110.0, "EquityMethodInvestments": 15.0,
                  "Deposits": 10.0, "Assets": 1000.0}
        fin = statements.sec_financial_assets("us-gaap", values.get)
        self.assertEqual(fin["cash"], 430.0)
        self.assertEqual(fin["other"], 70.0 + max(20.0, 110.0 - 15.0 - 70.0))
        self.assertEqual(fin["liab"], 0.0)
        self.assertAlmostEqual(fin["share"], 0.01)
        self.assertEqual(fin["tags"]["securities_current"], "ShortTermInvestments")

    def test_ifrs_sums_distinct_lines(self):
        values = {"CashAndCashEquivalents": 2000.0, "CurrentFinancialAssetsAtAmortisedCost": 100.0,
                  "OtherCurrentFinancialAssets": 60.0, "NoncurrentFinancialAssetsAtAmortisedCost": 90.0,
                  "NoncurrentFinancialAssetsMeasuredAtFairValueThroughOtherComprehensiveIncome": 8.0,
                  "CurrentFinancialLiabilitiesAtFairValueThroughProfitOrLoss": 3.0, "Assets": 6000.0}
        fin = statements.sec_financial_assets("ifrs-full", values.get)
        # OI-226：其他流动金融资产（台积电为应收政府补助等其他应收款）不计现金类
        self.assertEqual((fin["cash"], fin["other"], fin["liab"]), (2100.0, 98.0, 3.0))
        self.assertNotIn("OtherCurrentFinancialAssets", fin["tags"].values())

    def test_hong_kong_groups_keep_equity_method_in_capital(self):
        values = {"cash": 141.0, "restricted_cash": 7.0, "deposits": 236.8, "fvtpl_c": 44.7, "other_fin_c": 4.2,
                  "deposits_lt": 70.3, "fvtpl": 563.8, "other_fin_nc": 1.3, "fvl": 2.0, "other_fin_liab_c": 4.0,
                  "total_assets": 2039.0, "cust_deposits": 0.0}
        fin = statements.hk_financial_assets(values.get)
        self.assertAlmostEqual(fin["cash"], 141.0 + 7.0 + 236.8 + 44.7 + 4.2)
        self.assertAlmostEqual(fin["other"], 70.3 + 563.8 + 1.3)
        self.assertAlmostEqual(fin["liab"], 6.0)
        self.assertEqual(fin["share"], 0.0)


class EbitTest(unittest.TestCase):
    def test_operating_income_plus_equity_method(self):
        parts = {"operating_income": 129.0, "nonop_total": 29.8, "equity_method_income": 0.0}
        self.assertEqual(statements.nonop_ebit(parts.get, 158.8, 0.7), (129.0, "operating"))

    def test_operating_below_pretax_is_kept(self):
        parts = {"operating_income": -2.21, "nonop_total": 3.26}      # 营业外收益（剥离收益）不回到 EBIT
        self.assertEqual(statements.nonop_ebit(parts.get, 1.56, 1.09), (-2.21, "operating"))

    def test_segment_total_is_detected(self):
        # 迪士尼：无维度申报的分部经营利润合计高于税前利润，远超已识别的营业外费用 → 税前利润 − 净利息
        parts = {"operating_income": 17.551, "nonop_total": 0.0, "equity_method_income": 0.295, "net_interest": -1.305}
        ebit, source = statements.nonop_ebit(parts.get, 12.003, 1.81)
        self.assertEqual(source, "pretax_strip")
        self.assertAlmostEqual(ebit, 13.308)

    def test_identified_charges_keep_operating(self):
        parts = {"operating_income": 1.99, "other_nonop": -0.12}      # 债务清偿损失等营业外费用
        self.assertEqual(statements.nonop_ebit(parts.get, 1.15, 0.75)[1], "operating")

    def test_hong_kong(self):
        parts = {"operating_income": 241.6, "investment_gains": -3.2, "equity_method_income": 23.7, "interest_income": 16.9}
        self.assertAlmostEqual(statements.hk_ebit(parts.get)[0], 241.6 + 3.2 + 23.7)
        parts = {"pretax": 51.6, "interest_expense": 2.0, "interest_income": 2.6, "investment_gains": 3.6}
        self.assertEqual(statements.hk_ebit(parts.get), (51.6 + 2.0 - 2.6 - 3.6, "pretax_strip"))


class RowTest(unittest.TestCase):
    def build(self, **kw):
        return statements._build_row("US", "T", "T", "2025-12-31", "2026-02-01", "USD", 1000.0, 90.0, 100.0, 21.0, 5.0,
                                     kw.pop("equity", 400.0), 400.0, 0.0, 100.0, 500.0, 0, 0, 0, 10.0, {}, "test", 0.21, **kw)

    def test_excess_cash_liabilities_and_floor(self):
        row = self.build(ebit=90.0, ebit_source="operating", financial=dict(other=80.0, liab=7.0))
        self.assertEqual(row["excess_cash"], 500.0 - 20.0 + 80.0)
        self.assertEqual(row["interest_debt"], 107.0)
        self.assertEqual(row["invested_capital"], statements.IC_FLOOR * 400.0)   # 107 + 400 − 560 < 0 → 下限
        self.assertAlmostEqual(row["nopat"], 90.0 * (1 - 0.21))

    def test_missing_ebit_is_marked_legacy(self):
        row = self.build()
        self.assertEqual((row["ebit"], row["ebit_source"]), (105.0, "legacy"))

    def test_override_carries_latest_annual(self):
        annual = self.build(ebit=90.0, financial=dict(other=70.0))
        ttm = self.build(ebit=90.0, financial=dict(other=None), other_given=False)
        ttm["period"], ttm["period_type"] = "2026-06-30", "ttm"
        statements.carry_other_financial_assets([ttm], [annual])
        self.assertEqual(ttm["other_financial_assets"], 70.0)
        self.assertEqual(ttm["excess_cash"], annual["excess_cash"])
        stale = copy.deepcopy(ttm)
        stale.update(period="2027-06-30", other_financial_assets=0.0, _other_given=False, tags_used="")
        statements.carry_other_financial_assets([stale], [annual])
        self.assertEqual(stale["other_financial_assets"], 0.0)


def model_years(share=None):
    years = []
    for i, period in enumerate(("2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31")):
        y = roic_inputs.RoicYear(period=period, notice_date=period)
        y.revenue, y.ebit, y.nopat, y.tax_rate = 1000.0, 150.0, 120.0 + 5 * i, 0.2
        y.total_equity = y.parent_equity = 500.0 + 20 * i
        y.minority_equity, y.interest_debt, y.excess_cash = 0.0, 100.0, 50.0
        y.invested_capital = 550.0 + 20 * i
        y.capex, y.dep_amort, y.cfo, y.interest_expense = 60.0, 40.0, 130.0, 4.0
        y.shares, y.parent_netprofit, y.dividends_paid = 100.0, 100.0 + 5 * i, 80.0
        y.intermediation_share = share
        years.append(y)
    return years


class EngineTest(unittest.TestCase):
    def test_parameters_do_not_depend_on_tier(self):
        l1 = bands.value_company("T", "L1", model_years(), {})
        l3 = bands.value_company("T", "L3", model_years(), {})
        self.assertEqual(l1["status"], "ok")
        self.assertEqual((l1["r"], l1["value"]), (bands.REQUIRED_RETURN, l3["value"]))
        self.assertAlmostEqual(l1["roic_t"], min(l1["wacc"] + bands.TERMINAL_EXCESS, l1["roic0"]))

    def test_class_finance_is_unvaluable(self):
        result = bands.value_company("T", "L2", model_years(share=0.25), {})
        self.assertEqual(result["status"], "rejected")
        self.assertIn("类金融", result["reason"])


if __name__ == "__main__":
    unittest.main()
