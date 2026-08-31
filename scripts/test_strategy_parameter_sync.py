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
        # v4.92 SPA：候选侧买入线 0.9343、换仓边际 0.1437
        self.assertEqual(daily_scan.SEC93_BUY_LINE, 0.9343)
        self.assertEqual(daily_scan.SEC93_SWAP_MARGIN, 0.1437)
        # v4.109（OI-110）：估值减持线已删除，生产侧不得再有该常量
        self.assertFalse(hasattr(daily_scan, "SEC93_SELL_LINE"))
        self.assertEqual(daily_scan.DEFAULT_HOLD_BANDS, ROOT / "data/processed/a_share_pool_model_bands_hold.csv")

    def test_backtest_baseline_matches_production(self) -> None:
        args = shlex.split(sweep.BASE)
        self.assertEqual(float(option_value(args, "--max-corr")), daily_scan.SEC93_MAX_CORR)
        self.assertEqual(float(option_value(args, "--x")) / 100, daily_scan.SEC93_TRANCHE_PCT)
        # 两条线（v4.20 起入测——track_holdings 的线曾漂移三个月无人发现）；v4.34 起生产值 = 对齐解四位小数、不取整（§12.1）
        self.assertAlmostEqual(1 - float(option_value(args, "--width")), daily_scan.SEC93_BUY_LINE, places=4)
        self.assertEqual(float(option_value(args, "--swap-margin")), daily_scan.SEC93_SWAP_MARGIN)
        # v4.109（OI-110）：BASE 不得带 `--sell-line`——给了就把估值减持重新打开
        self.assertNotIn("--sell-line", args)
        # v4.92 SPA：候选侧与持仓侧逐日状态都显式入 BASE（`--hold-states` 缺省 None = 持仓侧同候选侧，会静默退回旧口径）
        self.assertEqual(option_value(args, "--daily-states"), "data/processed/a_share_daily_states_adopted.csv")
        self.assertEqual(option_value(args, "--hold-states"), "data/processed/a_share_daily_states_hold.csv")
        import track_holdings_daily
        # v4.44：涨幅减持 125%（gated）与融资口径（66.6%、不设金额上限）
        self.assertEqual(daily_scan.SEC93_GAIN_SELL, 1.25)
        self.assertEqual(float(option_value(args, "--gain-sell")), daily_scan.SEC93_GAIN_SELL)
        self.assertEqual(option_value(args, "--gain-sell-mode"), "gated")
        self.assertEqual(track_holdings_daily.GAIN_SELL, daily_scan.SEC93_GAIN_SELL)
        self.assertEqual(float(option_value(args, "--credit-ratio")), 0.666)
        self.assertGreaterEqual(float(option_value(args, "--credit-cap")), 1e11)   # 不设金额上限
        self.assertEqual(option_value(args, "--swap-trigger"), "power")
        self.assertEqual(option_value(args, "--credit-over-limit"), "repay")
        # v4.64：单票机械上限 60%（只挡加仓），生产常量与回测 BASE 同值
        self.assertEqual(daily_scan.SEC93_POSITION_CAP, 0.60)
        self.assertEqual(float(option_value(args, "--position-cap")), daily_scan.SEC93_POSITION_CAP)
        # v4.68（OI-092，§12.126）：三处时点/阈值口径显式入 BASE，防缺省漂移
        self.assertEqual(option_value(args, "--entry-below-ma60"), "ma60_stop")
        self.assertEqual(option_value(args, "--stop-basis"), "exec")
        self.assertEqual(option_value(args, "--residual-clear"), "lot")
        # 审计批 C：T+1 无价跳过、股息税、配股事件（不给 --no-rights-events）
        self.assertEqual(option_value(args, "--fill-missing"), "skip")
        self.assertIn("--dividend-tax", args)
        self.assertNotIn("--no-rights-events", args)
        self.assertEqual(option_value(args, "--swap-repeat"), "skip")

    def test_workflow_current_table_matches_production(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("| 相关性 | 与在手及已选标的近 252 日相关性 `≤ 0.70`", workflow)
        self.assertIn("| 单次买入 | 当日净资产 `N × 5.0%` |", workflow)
        self.assertIn(f"| 买入线 | `P/V ≤ {daily_scan.SEC93_BUY_LINE:.4f}` |", workflow)
        self.assertNotIn("| 减持 |", workflow)                # v4.109（OI-110）：估值减持行已删
        self.assertIn("`data/processed/a_share_daily_states_hold.csv`（持仓侧，`--hold-states`", workflow)
        self.assertIn("`data/processed/a_share_pool_model_bands_hold.csv`", workflow)
        self.assertIn(f"| 涨幅减持 | 收盘较持仓均价涨幅 `≥ {daily_scan.SEC93_GAIN_SELL:.0%}`", workflow)
        self.assertIn("授信 = 净资产 × 66.6%，不设金额上限", workflow)
        self.assertIn(f"| 单票机械上限 | 单票市值 ÷ 当日净资产 `N` ≥ {daily_scan.SEC93_POSITION_CAP:.0%} 时不再加仓", workflow)
        # v4.68/v4.69（OI-092）：§9.3 成文与回测实现同口径的关键句
        self.assertIn("| 新建仓走势 | T 日 `收盘 > MA20 > MA60` |", workflow)
        self.assertIn("现价跌破当日生效线即**当日**整仓清空", workflow)
        self.assertIn("任何减档后的余仓不足一手时清空", workflow)
        self.assertTrue(daily_scan.SEC93_L3_TACTICAL_GATE)
        self.assertIn("| L3 战术闸门 | `quality_tier = L3` 且分层表 `tactical_thesis` 为空或判「无／暂无／不可买」者不进合格集", workflow)

    def test_l3_tactical_gate_reads_tiers(self) -> None:
        import csv, tempfile
        from pathlib import Path
        rows = [
            {"security_code": "1", "quality_tier": "L3", "tactical_thesis": ""},
            {"security_code": "2", "quality_tier": "L3", "tactical_thesis": "**无**。理由"},
            {"security_code": "3", "quality_tier": "L3", "tactical_thesis": "暂无战术理由"},
            {"security_code": "4", "quality_tier": "L3", "tactical_thesis": "**有（条件式）**：..."},
            {"security_code": "5", "quality_tier": "L2", "tactical_thesis": ""},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tiers.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                writer.writeheader(); writer.writerows(rows)
            self.assertEqual(daily_scan.load_tactical_gate_codes(path), {"000001", "000002", "000003"})


if __name__ == "__main__":
    unittest.main()
