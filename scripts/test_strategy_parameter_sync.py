#!/usr/bin/env python3
"""Regression checks for the adopted §9.3 production parameters."""

from __future__ import annotations

import shlex
import unittest
from pathlib import Path

import screen_daily_volume_price_signals as daily_scan
import sweep_backtest_configs as sweep


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs/000_Ashare_workflow.md"


def option_value(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]


class StrategyParameterSyncTest(unittest.TestCase):
    def test_adopted_production_values(self) -> None:
        self.assertEqual(daily_scan.SEC93_MAX_CORR, 0.70)
        self.assertEqual(daily_scan.SEC93_TRANCHE_PCT, 0.05)

    def test_backtest_baseline_matches_production(self) -> None:
        args = shlex.split(sweep.BASE)
        self.assertEqual(float(option_value(args, "--max-corr")), daily_scan.SEC93_MAX_CORR)
        self.assertEqual(float(option_value(args, "--x")) / 100, daily_scan.SEC93_TRANCHE_PCT)
        # 三条线（v4.20 起入测——track_holdings 的减持线曾漂移三个月无人发现）；v4.33 起生产值只保留两位小数（§12.1）
        self.assertAlmostEqual(1 - float(option_value(args, "--width")), daily_scan.SEC93_BUY_LINE, places=4)
        self.assertEqual(float(option_value(args, "--sell-line")), daily_scan.SEC93_SELL_LINE)
        import track_holdings_daily
        self.assertEqual(track_holdings_daily.SELL_LINE, daily_scan.SEC93_SELL_LINE)

    def test_workflow_current_table_matches_production(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("| 相关性 | 与在手及已选标的近 252 日相关性 `≤ 0.70`", workflow)
        self.assertIn("| 单次买入 | 当日净资产 `N × 5.0%` |", workflow)
        self.assertIn(f"| 买入线 | `P/V ≤ {daily_scan.SEC93_BUY_LINE:.2f}` |", workflow)
        self.assertIn(f"| 减持 | `P/V ≥ {daily_scan.SEC93_SELL_LINE:.2f}` 且", workflow)


if __name__ == "__main__":
    unittest.main()
