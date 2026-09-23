#!/usr/bin/env python3
"""§6.5.1 超额回报衰减开关（OI-204）的回归测试。

Run: ``python3 scripts/test_fade_shape.py``

锁住五件事：
1. 缺省参数不含指数路径（生产由 §6.7 命令开启），建带传给引擎的参数与命令一致；
2. 指数形状只改回报路径：增速仍 n 年线性到 g_T、其后保持，终值按 n1 + horizon 年折现；
3. 终值占比按增速 fade 期末之后的现值计（§6.5.3）；
4. Bear／Bull 的 fade 年数扰动同比例改回报衰减速度（§6.5.3）；
5. 高起点回报时线性整本衰减在期末触界、指数路径不触界（茅台 2026 中报量级的判例）。
"""
from __future__ import annotations

import math
import sys
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_historical_valuation_bands as bands  # noqa: E402
from intrinsic_value import intrinsic_value  # noqa: E402


class FadeShapeTest(unittest.TestCase):
    def test_default_is_production(self) -> None:
        self.assertEqual(bands.fade_kwargs(Namespace()), dict(consistent=True))
        args = Namespace(fade_object="book", fade_shape="exponential", fade_lambda=0.12, fade_horizon=50)
        self.assertEqual(bands.fade_kwargs(args), dict(consistent=True, roe_lam=0.12, horizon=50))

    def test_exponential_changes_only_the_return_path(self) -> None:
        res = intrinsic_value(1.0, 0.40, 0.08, 0.10, roe_terminal=0.12, roe_lam=0.12, horizon=50)
        self.assertEqual(len(res.roe_path), 50)
        expected = [0.12 + 0.28 * math.exp(-0.12 * t) for t in range(1, 51)]
        self.assertTrue(all(abs(a - b) < 1e-12 for a, b in zip(res.roe_path, expected)))
        self.assertTrue(all(abs(g - 0.03) < 1e-12 for g in res.g_path[10:]))
        linear = intrinsic_value(1.0, 0.40, 0.08, 0.10, roe_terminal=0.12)
        self.assertEqual(len(linear.roe_path), 10)

    def test_terminal_share_counts_years_after_growth_fade(self) -> None:
        res = intrinsic_value(1.0, 0.40, 0.08, 0.10, roe_terminal=0.12, roe_lam=0.12, horizon=50)
        head = sum(e * p / 1.10 ** t for t, (e, p) in enumerate(zip(res.eps_path, res.payout_path), start=1) if t <= 10)
        self.assertAlmostEqual(res.explicit_pv, head, places=12)
        self.assertAlmostEqual(res.terminal_share, 1 - head / res.intrinsic_value, places=12)
        self.assertGreater(res.terminal_share, 0.5)

    def test_sensitivity_scales_return_fade_with_fade_years(self) -> None:
        fade = dict(consistent=True, roe_lam=0.12, horizon=50)
        bear, bull = bands.sensitivity_values(1.0, 0.40, 0.08, 0.10, 0.12, 0.03, 10, 0, 0.25, 0.01, fade=fade)
        slow = intrinsic_value(1.0, 0.40, 0.10, 0.09, roe_terminal=0.13, g_terminal=0.035, n=13,
                               roe_lam=0.12 * 10 / 13, horizon=50)
        self.assertAlmostEqual(bull, slow.intrinsic_value, places=12)
        self.assertLess(bear, bull)

    def test_linear_cliff_and_exponential_smooth(self) -> None:
        linear = intrinsic_value(1.0, 1.63, 0.059, 0.094, roe_terminal=0.114)
        smooth = intrinsic_value(1.0, 1.63, 0.059, 0.094, roe_terminal=0.114, roe_lam=0.12, horizon=50)
        self.assertGreater(linear.clamped_years, 0)
        self.assertEqual(min(linear.payout_path), 0.0)
        self.assertEqual(smooth.clamped_years, 0)
        self.assertGreater(smooth.intrinsic_value, linear.intrinsic_value)


if __name__ == "__main__":
    unittest.main()
