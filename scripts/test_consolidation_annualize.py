#!/usr/bin/env python3
"""OI-132 购买法收购当年分子年化回归测试。

Run: ``python3 scripts/test_consolidation_annualize.py``
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import roic_inputs as ri  # noqa: E402


def _year(period: str, nopat: float, tax: float = 0.25) -> ri.RoicYear:
    y = ri.RoicYear(period=period, notice_date=f"{int(period[:4]) + 1}-04-20")
    y.tax_rate, y.nopat, y.ebit = tax, nopat, nopat / (1 - tax)
    y.parent_netprofit, y.net_profit = nopat * 0.9, nopat
    return y


class ConsolidatedMonthsTest(unittest.TestCase):
    def test_months_by_purchase_day(self):
        self.assertEqual(ri.consolidated_months("2025-09-01", "2025-12-31"), 4)    # 9~12 月
        self.assertEqual(ri.consolidated_months("2025-09-20", "2025-12-31"), 3)    # 15 日后不算 9 月
        self.assertEqual(ri.consolidated_months("2025-01-10", "2025-12-31"), 12)   # 1 月 15 日前 → 全年
        self.assertEqual(ri.consolidated_months("2025-01-20", "2025-12-31"), 11)
        self.assertEqual(ri.consolidated_months("2025-12-31", "2025-12-31"), 1)    # 夹在 1


class AnnualizeTest(unittest.TestCase):
    def _events(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "consolidation_events.csv"
            path.write_text(",".join(ri.CONSOLIDATION_FIELDS) + "\n" + text, encoding="utf-8")
            return ri.load_consolidation_events(path)

    def test_numerator_annualized_only_in_acquisition_year(self):
        years = {"000001": {"2024-12-31": _year("2024-12-31", 100.0), "2025-12-31": _year("2025-12-31", 130.0)}}
        events = self._events("000001,甲,乙,2025-09-01,2025-12-31,,80,30,年报附注,2026-09-02,\n")
        self.assertEqual(ri.annualize_consolidation(years, events), 1)
        y25, y24 = years["000001"]["2025-12-31"], years["000001"]["2024-12-31"]
        self.assertAlmostEqual(y25.nopat, 130.0 + 30.0 * (12 / 4 - 1))      # 4 个月并表 → 补 2 倍
        self.assertAlmostEqual(y25.ebit, y25.nopat / 0.75)
        self.assertEqual(y25.annualized_months, 4)
        self.assertAlmostEqual(y25.net_profit, 130.0)                     # 合并净利不动
        self.assertAlmostEqual(y24.nopat, 100.0)
        self.assertEqual(y24.annualized_months, 0)

    def test_explicit_months_override_and_superseded_versions(self):
        cur = _year("2025-12-31", 130.0)
        old = _year("2025-12-31", 120.0)
        cur.superseded = [("2026-08-26", old)]
        years = {"000001": {"2025-12-31": cur}}
        events = self._events("000001,甲,乙,2025-09-20,2025-12-31,6,0,12,年报附注,2026-09-02,\n")
        ri.annualize_consolidation(years, events)
        self.assertAlmostEqual(cur.nopat, 130.0 + 12.0)                   # 明示 6 个月 → 补 1 倍
        self.assertAlmostEqual(old.nopat, 120.0 + 12.0)
        ri.annualize_consolidation(years, events)                          # 幂等：已调整的行不重复加
        self.assertAlmostEqual(cur.nopat, 142.0)

    def test_invalid_rows_are_skipped(self):
        events = self._events("000001,甲,乙,2025-09-01,2025-06-30,,80,30,,,\n"        # 非年报期
                              "000002,丙,丁,2025-12-31,2025-12-31,13,80,30,,,\n"       # 月数越界
                              "000003,戊,己,2025-09-01,2025-12-31,,80,,,,\n")           # 净利润缺失
        self.assertEqual(events, {})


if __name__ == "__main__":
    unittest.main()
