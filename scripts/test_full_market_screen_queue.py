#!/usr/bin/env python3
"""排队分层与升级预筛守卫的回归测试（OI-036 2026-08-30 登记的三项预筛缺陷）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_full_market_screen_queue import (
    tier_inputs,
    classify,
    deduct_ratio,
    in_ipo_roe_window,
    ocf_to_eps,
)


class ClassifyTest(unittest.TestCase):
    def test_revenue_threshold_still_wins_regardless_of_ipo_window(self) -> None:
        tier, _ = classify(45.0, 5.0, 30.0, "某大盘股", ipo_roe_window=True)
        self.assertEqual(tier, "A_核心")

    def test_roe_only_path_is_withheld_inside_the_ipo_window(self) -> None:
        tier, reason = classify(12.0, 2.0, 25.0, "某北交所新股", ipo_roe_window=True)
        self.assertEqual(tier, "B_观察")
        self.assertIn("上市前小净资产口径", reason)

    def test_roe_only_path_applies_for_seasoned_companies(self) -> None:
        tier, _ = classify(12.0, 2.0, 25.0, "某老公司", ipo_roe_window=False)
        self.assertEqual(tier, "A_核心")

    def test_risk_warning_and_scale_rules_unchanged(self) -> None:
        self.assertEqual(classify(50.0, 5.0, 20.0, "*ST某某")[0], "C_排除")
        self.assertEqual(classify(None, None, None, "某某")[0], "C_排除")
        self.assertEqual(classify(3.0, 1.0, 20.0, "某小盘")[0], "C_排除")
        self.assertEqual(classify(20.0, -1.0, None, "某亏损")[0], "C_排除")
        self.assertEqual(classify(12.0, 1.0, 8.0, "某中盘")[0], "B_观察")


class IpoWindowTest(unittest.TestCase):
    def test_listing_year_and_following_year_are_inside(self) -> None:
        self.assertTrue(in_ipo_roe_window("2025-03-01"))
        self.assertTrue(in_ipo_roe_window("2024-07-15"))

    def test_older_listings_are_outside(self) -> None:
        self.assertFalse(in_ipo_roe_window("2023-12-31"))
        self.assertFalse(in_ipo_roe_window("1999-11-10"))

    def test_missing_or_malformed_date_is_outside(self) -> None:
        for value in ("", "n/a", "----"):
            self.assertFalse(in_ipo_roe_window(value))


class NonRecurringGuardTest(unittest.TestCase):
    def test_deduct_ratio_flags_non_recurring_driven_profit(self) -> None:
        self.assertAlmostEqual(deduct_ratio({"basic_eps": "2.61", "deduct_basic_eps": "1.25"}), 47.89, places=1)
        self.assertAlmostEqual(deduct_ratio({"basic_eps": "2.06", "deduct_basic_eps": "1.98"}), 96.12, places=1)

    def test_cash_conversion_ratio(self) -> None:
        self.assertAlmostEqual(ocf_to_eps({"basic_eps": "4.02", "op_cashflow_ps": "-0.22"}), -0.0547, places=3)
        self.assertAlmostEqual(ocf_to_eps({"basic_eps": "2.06", "op_cashflow_ps": "2.53"}), 1.2282, places=3)

    def test_missing_and_zero_inputs_return_none(self) -> None:
        for bad in (None, {}, {"basic_eps": "0", "deduct_basic_eps": "1"}, {"basic_eps": "1"}):
            self.assertIsNone(deduct_ratio(bad))
            self.assertIsNone(ocf_to_eps(bad))


class TierInputsTest(unittest.TestCase):
    """分层入参的 TTM 口径与兜底链。金额单位元，返回值单位亿。"""

    @staticmethod
    def _panels(**periods):
        return {name: ({"000001": row} if row else {}) for name, row in periods.items()}

    def test_ttm_rolls_current_plus_prior_annual_minus_prior_same_period(self) -> None:
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "60e8",
                           "parent_netprofit": "6e8", "weightavg_roe": "7", "basic_eps": "0.6"},
            "2025-12-31": {"notice_date": "2026-04-20", "total_operate_income": "100e8",
                           "parent_netprofit": "10e8", "weightavg_roe": "12", "basic_eps": "1.0"},
            "2025-06-30": {"notice_date": "2025-08-27", "total_operate_income": "40e8",
                           "parent_netprofit": "4e8", "weightavg_roe": "5", "basic_eps": "0.4"},
        })
        rev, prof, roe, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(rev, 120.0)      # 60 + 100 − 40
        self.assertAlmostEqual(prof, 12.0)
        self.assertAlmostEqual(roe, 14.0)       # 7 + 12 − 5

    def test_half_year_input_alone_would_understate_tier(self) -> None:
        """中报 60 亿单看不到 30 亿线以上的真实规模——TTM 的存在意义。"""
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "20e8",
                           "parent_netprofit": "2e8", "weightavg_roe": "4", "basic_eps": "0.2"},
            "2025-12-31": {"notice_date": "2026-04-20", "total_operate_income": "45e8",
                           "parent_netprofit": "5e8", "weightavg_roe": "11", "basic_eps": "0.5"},
            "2025-06-30": {"notice_date": "2025-08-27", "total_operate_income": "22e8",
                           "parent_netprofit": "2.4e8", "weightavg_roe": "5", "basic_eps": "0.24"},
        })
        rev, _, _, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(rev, 43.0)       # 折年会给 40，年报给 45，TTM 给 43

    def test_falls_back_to_prior_annual_when_ttm_leg_missing(self) -> None:
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "60e8",
                           "parent_netprofit": "6e8", "weightavg_roe": "7", "basic_eps": "0.6"},
            "2025-12-31": {"notice_date": "2026-04-20", "total_operate_income": "100e8",
                           "parent_netprofit": "10e8", "weightavg_roe": "12", "basic_eps": "1.0"},
            "2025-06-30": None,
        })
        rev, prof, roe, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "annual")
        self.assertAlmostEqual(rev, 100.0)
        self.assertAlmostEqual(prof, 10.0)
        self.assertAlmostEqual(roe, 12.0)

    def test_annualizes_only_when_ttm_and_annual_both_missing(self) -> None:
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "9e8",
                           "parent_netprofit": "1e8", "weightavg_roe": "6", "basic_eps": "0.3"},
            "2025-12-31": None, "2025-06-30": None,
        })
        rev, prof, roe, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "annualized")
        self.assertAlmostEqual(rev, 18.0)
        self.assertAlmostEqual(prof, 2.0)
        self.assertAlmostEqual(roe, 12.0)

    def test_first_quarter_annualizes_by_four(self) -> None:
        panels = self._panels(**{
            "2026-03-31": {"notice_date": "2026-04-25", "total_operate_income": "3e8",
                           "parent_netprofit": "0.5e8", "weightavg_roe": "2", "basic_eps": "0.1"},
            "2025-12-31": None, "2025-03-31": None,
        })
        rev, _, roe, basis = tier_inputs(panels, "000001", "2026-03-31")
        self.assertEqual(basis, "annualized")
        self.assertAlmostEqual(rev, 12.0)
        self.assertAlmostEqual(roe, 8.0)

    def test_restated_prior_period_falls_back_to_annual(self) -> None:
        """上年同期累计营收大于上年年报＝两期口径不同，TTM 会滚出负营收，须退回年报。"""
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "7.6e8",
                           "parent_netprofit": "1e8", "weightavg_roe": "3", "basic_eps": "0.5"},
            "2025-12-31": {"notice_date": "2026-04-20", "total_operate_income": "18.5e8",
                           "parent_netprofit": "2e8", "weightavg_roe": "5", "basic_eps": "1.0"},
            "2025-06-30": {"notice_date": "2025-08-27", "total_operate_income": "55.6e8",
                           "parent_netprofit": "1.2e8", "weightavg_roe": "3", "basic_eps": "0.6"},
        })
        rev, _, roe, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "annual")
        self.assertAlmostEqual(rev, 18.5)       # 若不拦截，TTM = 7.6 + 18.5 − 55.6 = −29.5
        self.assertAlmostEqual(roe, 5.0)

    def test_equal_prior_period_and_annual_still_rolls(self) -> None:
        """边界：上年同期等于上年年报（下半年零营收）不算口径不一致。"""
        panels = self._panels(**{
            "2026-06-30": {"notice_date": "2026-08-28", "total_operate_income": "12e8",
                           "parent_netprofit": "1e8", "weightavg_roe": "3", "basic_eps": "0.5"},
            "2025-12-31": {"notice_date": "2026-04-20", "total_operate_income": "10e8",
                           "parent_netprofit": "1e8", "weightavg_roe": "4", "basic_eps": "0.5"},
            "2025-06-30": {"notice_date": "2025-08-27", "total_operate_income": "10e8",
                           "parent_netprofit": "0.8e8", "weightavg_roe": "3", "basic_eps": "0.4"},
        })
        rev, _, _, basis = tier_inputs(panels, "000001", "2026-06-30")
        self.assertEqual(basis, "ttm")
        self.assertAlmostEqual(rev, 12.0)

    def test_no_usable_period_returns_empty_basis(self) -> None:
        self.assertEqual(tier_inputs({}, "000001", "2026-06-30"), (None, None, None, ""))


if __name__ == "__main__":
    unittest.main()
