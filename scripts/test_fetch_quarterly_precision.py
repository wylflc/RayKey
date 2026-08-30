#!/usr/bin/env python3
"""重取时的精度守卫（2026-08-31 全历史回填时源端把北交所 bps 由 12 位截成 2 位）。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_a_share_quarterly_financials import is_rounding_of, keep_precision


class IsRoundingOfTest(unittest.TestCase):
    def test_detects_precision_loss(self) -> None:
        self.assertTrue(is_rounding_of("0.840000", "0.836756"))     # 智诺科技，2 位
        self.assertTrue(is_rounding_of("1.200000", "1.198995"))     # 高速传媒
        self.assertTrue(is_rounding_of("0.960000", "0.956470"))     # 裕荣光电
        self.assertTrue(is_rounding_of("6.070000", "6.066323"))     # 能拓股份
        self.assertTrue(is_rounding_of("-0.280000", "-0.283939"))   # ST烜风，负值

    def test_real_restatement_is_not_rounding(self) -> None:
        self.assertFalse(is_rounding_of("25.76959081987", "20.590215914238"))   # 中国神华
        self.assertFalse(is_rounding_of("21.047194792698", "17.041518597494"))  # 电投能源

    def test_equal_or_more_precise_new_value_is_not_rounding(self) -> None:
        self.assertFalse(is_rounding_of("0.836756", "0.836756"))
        self.assertFalse(is_rounding_of("0.8367561", "0.836756"))

    def test_non_numeric_is_not_rounding(self) -> None:
        for new, old in (("", "0.83"), ("0.83", ""), ("n/a", "0.83"), ("0.83", "—")):
            self.assertFalse(is_rounding_of(new, old))


class KeepPrecisionTest(unittest.TestCase):
    FIELDS = ("security_code", "bps", "basic_eps", "parent_netprofit")

    def _file(self, rows) -> Path:
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                         newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=self.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        fh.close()
        return Path(fh.name)

    def test_restores_rounded_cells_only(self) -> None:
        path = self._file([
            {"security_code": "837181", "bps": "0.836756", "basic_eps": "0.1234567",
             "parent_netprofit": "12345678"},
            {"security_code": "601088", "bps": "20.590215914238", "basic_eps": "1.24",
             "parent_netprofit": "24641000000"},
        ])
        rows = [
            {"security_code": "837181", "bps": "0.840000", "basic_eps": "0.1234567",
             "parent_netprofit": "12345678"},
            {"security_code": "601088", "bps": "25.76959081987", "basic_eps": "1.302",
             "parent_netprofit": "27583000000"},
        ]
        restored = keep_precision(rows, path)
        self.assertEqual(restored, 1)
        self.assertEqual(rows[0]["bps"], "0.836756")     # 精度换回
        self.assertEqual(rows[1]["bps"], "25.76959081987")   # 真重述保留新值
        self.assertEqual(rows[1]["basic_eps"], "1.302")

    def test_unguarded_field_is_never_touched(self) -> None:
        """`parent_netprofit` 不在守卫列表里：整数级金额不存在精度降级问题。"""
        path = self._file([{"security_code": "000001", "bps": "1.0", "basic_eps": "1.0",
                            "parent_netprofit": "1234567.89"}])
        rows = [{"security_code": "000001", "bps": "1.0", "basic_eps": "1.0",
                 "parent_netprofit": "1234568"}]
        self.assertEqual(keep_precision(rows, path), 0)
        self.assertEqual(rows[0]["parent_netprofit"], "1234568")

    def test_new_code_and_missing_file_are_safe(self) -> None:
        path = self._file([{"security_code": "000001", "bps": "1.234567",
                            "basic_eps": "", "parent_netprofit": ""}])
        rows = [{"security_code": "999999", "bps": "1.23", "basic_eps": "", "parent_netprofit": ""}]
        self.assertEqual(keep_precision(rows, path), 0)
        self.assertEqual(keep_precision(rows, Path("/nonexistent/x.csv")), 0)


if __name__ == "__main__":
    unittest.main()
