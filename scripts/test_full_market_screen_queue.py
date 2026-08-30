#!/usr/bin/env python3
"""排队分层与升级预筛守卫的回归测试（OI-036 2026-08-30 登记的三项预筛缺陷）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_full_market_screen_queue import (
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


if __name__ == "__main__":
    unittest.main()
