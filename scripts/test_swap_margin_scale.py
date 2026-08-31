#!/usr/bin/env python3
"""OI-114：换仓边际两种标度（绝对差／相对差）的判据回归。"""

from __future__ import annotations

import unittest

import backtest_valuation_strategy as bt
import sweep_backtest_configs as sweep


M = 0.19                       # 现行换仓边际（v4.113）


class SwapMarginScaleTest(unittest.TestCase):
    def test_abs_is_the_current_expression(self) -> None:
        """`abs` 必须逐位等于重构前的 `ref − cand >= margin`。"""
        for ref, cand in ((1.0, 0.85), (1.0, 0.86), (0.6, 0.4563), (3.2, 3.0563), (0.5, 0.9)):
            self.assertEqual(bt.swap_margin_gap_ok(ref, cand, M),
                             ref - cand >= M, f"{ref}/{cand}")

    def test_ratio_is_scale_invariant_and_abs_is_not(self) -> None:
        """OI-114 的动机：两侧 `P/V` 同倍缩放时，相对判据不变、绝对判据会翻转。"""
        ref, cand = 1.0, 0.75      # 非边界：gap 0.25 > M，缩放后判据才可比
        for k in (0.5, 2.0, 5.0):
            self.assertEqual(bt.swap_margin_gap_ok(ref * k, cand * k, M, "ratio"),
                             bt.swap_margin_gap_ok(ref, cand, M, "ratio"), f"k={k}")
        # 绝对判据在 k=0.5 上由成立翻成不成立
        self.assertTrue(bt.swap_margin_gap_ok(ref, cand, M))
        self.assertFalse(bt.swap_margin_gap_ok(ref * 0.5, cand * 0.5, M))

    def test_ratio_tightens_above_pv_one_and_loosens_below(self) -> None:
        """同一数值的边际：源 `P/V` > 1 时相对更严，< 1 时相对更松。"""
        self.assertLess(bt.swap_margin_gap_floor(2.0, M, "ratio"),
                        bt.swap_margin_gap_floor(2.0, M, "abs"))
        self.assertGreater(bt.swap_margin_gap_floor(0.6, M, "ratio"),
                           bt.swap_margin_gap_floor(0.6, M, "abs"))

    def test_floor_and_predicate_agree(self) -> None:
        """下限式与判据式必须同侧。边界点本身不断言：`ref − (ref − m)` 在浮点上不恒等于 `m`，
        活路径因此保留判据式原样，只有本来就求下限的两处研究开关用下限式。"""
        for mode in ("abs", "ratio"):
            for ref in (0.4, 0.65, 1.0, 2.5):
                floor = bt.swap_margin_gap_floor(ref, M, mode)
                self.assertTrue(bt.swap_margin_gap_ok(ref, floor - 1e-9, M, mode), (mode, ref))
                self.assertFalse(bt.swap_margin_gap_ok(ref, floor + 1e-9, M, mode), (mode, ref))

    def test_base_stays_on_the_absolute_scale(self) -> None:
        """`BASE` 不得携带 `--swap-margin-mode`：缺省 abs 即现行生产口径。"""
        self.assertNotIn("--swap-margin-mode", sweep.BASE)
        self.assertIn("--swap-margin 0.19", sweep.BASE)


if __name__ == "__main__":
    unittest.main(verbosity=0)
