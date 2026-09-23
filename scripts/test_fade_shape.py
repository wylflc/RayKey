#!/usr/bin/env python3
"""§6.5.1 超额回报衰减开关（OI-204）的回归测试。

Run: ``python3 scripts/test_fade_shape.py``

锁住三件事：
1. 缺省参数与生产一致（整本线性衰减），建带传给引擎的参数不含指数路径；
2. 指数形状只改回报路径：增速仍 n 年线性到 g_T、其后保持，终值按 n1 + horizon 年折现；
3. 高起点回报时线性整本衰减在期末触界、指数路径不触界（茅台 2026 中报量级的判例）。
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

    def test_linear_cliff_and_exponential_smooth(self) -> None:
        linear = intrinsic_value(1.0, 1.63, 0.059, 0.094, roe_terminal=0.114)
        smooth = intrinsic_value(1.0, 1.63, 0.059, 0.094, roe_terminal=0.114, roe_lam=0.12, horizon=50)
        self.assertGreater(linear.clamped_years, 0)
        self.assertEqual(min(linear.payout_path), 0.0)
        self.assertEqual(smooth.clamped_years, 0)
        self.assertGreater(smooth.intrinsic_value, linear.intrinsic_value)


if __name__ == "__main__":
    unittest.main()
