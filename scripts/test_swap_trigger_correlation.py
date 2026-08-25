#!/usr/bin/env python3
"""OI-101：换仓触发候选的相关性预过滤回归。"""

from __future__ import annotations

import unittest

import backtest_valuation_strategy as bt


class FakeCorrelations:
    def __init__(self, values):
        self.values = {frozenset(pair): value for pair, value in values.items()}

    def get(self, a: str, b: str, day: str):
        return 1.0 if a == b else self.values.get(frozenset((a, b)))


class SwapTriggerCorrelationTest(unittest.TestCase):
    def test_only_currently_buyable_candidates_survive(self) -> None:
        rows = [
            ("HELD", 1.0, 1.0, 0.50),
            ("X1", 1.0, 1.0, 0.60),
            ("X2", 1.0, 1.0, 0.70),
            ("X3", 1.0, 1.0, 0.80),
        ]
        corr = FakeCorrelations({
            ("HELD", "X1"): 0.90,   # 与在手持仓冲突
            ("HELD", "X2"): 0.20,
            ("HELD", "X3"): 0.20,
            ("X2", "X3"): 0.85,     # 与已选的未持仓候选冲突
        })
        got = bt.correlation_skip_buyable_codes(
            rows, {"HELD"}, corr, "2026-08-25", 0.70, 40, 999)
        self.assertEqual(got, {"HELD", "X2"})

    def test_unknown_correlation_passes_and_scan_depth_is_hard(self) -> None:
        rows = [
            ("X1", 1.0, 1.0, 0.50),
            ("X2", 1.0, 1.0, 0.60),
            ("X3", 1.0, 1.0, 0.70),
        ]
        got = bt.correlation_skip_buyable_codes(
            rows, set(), FakeCorrelations({}), "2026-08-25", 0.70, 2, 999)
        self.assertEqual(got, {"X1", "X2"})


if __name__ == "__main__":
    unittest.main()
