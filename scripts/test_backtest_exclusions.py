#!/usr/bin/env python3
"""Regression tests for the winner-exclusion research switch."""
import unittest

from backtest_valuation_strategy import parse_excluded_codes


class ExcludedCodesTest(unittest.TestCase):
    def test_parse_trims_and_deduplicates(self) -> None:
        self.assertEqual(parse_excluded_codes("000933, 002128,000933"),
                         {"000933", "002128"})

    def test_empty_list_keeps_default_path(self) -> None:
        self.assertEqual(parse_excluded_codes(""), set())

    def test_invalid_code_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "6 位数字"):
            parse_excluded_codes("000933,SH601225")


if __name__ == "__main__":
    unittest.main()
