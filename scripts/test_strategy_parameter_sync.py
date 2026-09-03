#!/usr/bin/env python3
"""Regression checks for the adopted §9.3 production parameters."""

from __future__ import annotations

import shlex
import unittest
from pathlib import Path

import screen_daily_volume_price_signals as daily_scan
import sweep_backtest_configs as sweep
import backtest_valuation_strategy as bt


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "docs/000_Ashare_workflow.md"


def option_value(args: list[str], option: str) -> str:
    return args[args.index(option) + 1]


class StrategyParameterSyncTest(unittest.TestCase):
    def test_adopted_production_values(self) -> None:
        # v4.132（OI-136）：相关性只计算列报告、不过滤（上限 1.0 = 无一被跳过）
        self.assertEqual(daily_scan.SEC93_MAX_CORR, 1.0)
        self.assertEqual(daily_scan.SEC93_TRANCHE_PCT, 0.05)
        # 候选侧买入线 1.0454（OI-132 购买法收购当年分子年化后重解）；换仓边际 0.15（v4.133，§12.174 表 R／§12.176）
        self.assertEqual(daily_scan.SEC93_BUY_LINE, 1.0454)
        self.assertEqual(daily_scan.SEC93_SWAP_MARGIN, 0.15)
        self.assertEqual(daily_scan.SEC93_SWAP_SOURCE_BLOCK, -1.0)  # 换仓接收方守卫关（v4.137 回退 v4.135）
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
        self.assertEqual(float(option_value(args, "--swap-source-block")), daily_scan.SEC93_SWAP_SOURCE_BLOCK)
        # v4.109（OI-110）：BASE 不得带 `--sell-line`——给了就把估值减持重新打开
        self.assertNotIn("--sell-line", args)
        # v4.92 SPA：候选侧与持仓侧逐日状态都显式入 BASE（`--hold-states` 缺省 None = 持仓侧同候选侧，会静默退回旧口径）
        self.assertEqual(option_value(args, "--daily-states"), "data/processed/a_share_daily_states_adopted.csv")
        self.assertEqual(option_value(args, "--hold-states"), "data/processed/a_share_daily_states_hold.csv")
        import track_holdings_daily
        # v4.132（OI-137）：涨幅减持 110% ungated（不看走势）；融资口径（66.6%、不设金额上限）
        self.assertEqual(daily_scan.SEC93_GAIN_SELL, 1.10)
        self.assertEqual(float(option_value(args, "--gain-sell")), daily_scan.SEC93_GAIN_SELL)
        self.assertEqual(option_value(args, "--gain-sell-mode"), "ungated")
        # v4.134（OI-142）：当日已涨幅减持的持仓不作换仓卖出源，BASE 显式带开关、不得带反向开关
        self.assertIn("--swap-gain-once", args)
        self.assertNotIn("--no-swap-gain-once", args)
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
        self.assertIn("| 相关性 | 只计算并在报告列出与在手及已选标的近 252 日相关性，不作过滤", workflow)
        self.assertNotIn("超限跳过", workflow)
        self.assertIn("| 单次买入 | 当日净资产 `N × 5.0%` |", workflow)
        self.assertIn(f"| 买入线 | `P/V ≤ {daily_scan.SEC93_BUY_LINE:.4f}` |", workflow)
        self.assertNotIn("| 减持 |", workflow)                # v4.109（OI-110）：估值减持行已删
        # v4.110（OI-116）：止盈行不得退回「无」——涨幅减持即按盈利触发的减仓
        self.assertIn("| 止盈 | 只有本表「涨幅减持」一条按盈利触发的减仓", workflow)
        self.assertNotIn("| 止盈 | 无 |", workflow)
        # v4.115（用户 2026-09-01）：全期 CAGR 的配对差为第五项决策读数，与主读数同为采纳门槛
        self.assertIn("复利读数 = **全期 CAGR** 的配对差中位；", workflow)
        # v4.129（OI-118／OI-119）：主读数与复利读数两表各取、−0.15pp／[−1pp, −0.15pp)＋≥+1pp 报用户裁定；正号数只报不判
        self.assertIn("坏情形、闸门、否决取全样本表；**主读数与复利读数在全样本表与去赢家表（剔除集 A）各取一份，四个读数按下式判**", workflow)
        self.assertIn("均 ≥ −0.15pp → 可采纳；一表的某项落在 [−1pp, −0.15pp) 且另一表同项 ≥ +1pp → 报用户裁定；其余不采纳。正号起点数只报不判。", workflow)
        self.assertNotIn("任一为负即不采纳", workflow)
        self.assertIn("主读数与复利读数（全样本表）各自损失不超过 1pp", workflow)
        import sweep_backtest_configs as sweep_verdict
        self.assertEqual((sweep_verdict.NOISE_BAND, sweep_verdict.RULING_TOLERANCE, sweep_verdict.CLEAR_GAIN), (0.0015, 0.01, 0.01))
        # 扫描器的决策读数键须与成文同步（年化 = 全期 CAGR）
        import sweep_backtest_configs as sweep
        self.assertIn("年化", sweep.DELTA_KEYS)
        self.assertNotIn("年化", sweep.AUX_DELTA_KEYS)
        # v4.116（OI-122，§12.157）：臂间比较基准 = 复利读数、对照表按 Δ年化 排序；
        # 未来年化的水平引用只走全期口径，互不重叠 5 年块中位为必报描述读数
        self.assertIn("**臂间比较与「未来年化表现」的表述基准一律为复利读数**", workflow)
        self.assertIn("未来年化的水平引用只用全期口径读数", workflow)
        self.assertIn("互不重叠 5 年块中位（自最新窗口末月往回每 60 个月一窗、首尾相接零重叠，取中位）", workflow)
        self.assertIn("互不重叠5年块中位", sweep.FIELDS)
        self.assertEqual("年化", sweep.PRIMARY_KEY)
        # v4.117（§12.158/§12.160，用户 2026-09-02 裁定）：标准起点集 = 路径 ≥10 年的半年档起点，
        # 现 14 个；数据末端推进使新档满 10 年时补入并重登在册读数
        self.assertIn("标准起点集 = 路径长度 ≥ 10 年的全部半年档起点（现 14 个：2009-11-01 ~ 2016-05-01", workflow)
        self.assertIn("符号数是 14 个起点层", workflow)
        self.assertEqual(len(sweep.DEFAULT_STARTS), 14)
        self.assertEqual(sweep.DEFAULT_STARTS[0], "2009-11-01")
        self.assertEqual(sweep.DEFAULT_STARTS[-1], "2016-05-01")
        self.assertIn(sweep.EX5_ANCHOR_START, sweep.DEFAULT_STARTS)
        for anchor in sweep.LONGRUN_STARTS:
            self.assertIn(anchor, sweep.DEFAULT_STARTS)
        # 标准指标集入 §12.1 第 2 款：两个口径各出一份，每项报水平／配对差／变好起点数
        self.assertIn("**标准指标集**（每轮扫描必报，全样本与去赢家两个口径各出一份、同表并列", workflow)
        self.assertIn("长跑锚点是单起点，只报水平与配对差，不报符号数、不进任何判定", workflow)
        std = {name for name, *_rest in sweep.STANDARD_SET}
        for name in ("滚5中位", "滚5P25", "滚5最差", "滚5回撤", "滚5Calmar", "滚5Sharpe", "负窗%",
                     "年化", "最大回撤", "Calmar", "Sharpe", "5年块中位", "滚3中位", "滚3回撤",
                     "逐年中位", "逐年最差", "换手", "仓位"):
            self.assertIn(name, std)
        for _name, key, *_rest in sweep.STANDARD_SET:
            self.assertIn(key, sweep.FIELDS)
        # 去赢家剔除集取 A 与 U 两个；第 4 款「全面优秀」不构成采纳
        self.assertIn("剔除集取两个：**A** =", workflow)
        self.assertIn("按代码汇总逐日「盈亏 ÷ 前一日净资产」累计贡献的前五名", workflow)
        self.assertIn("contrib", bt.TRADE_FIELDS)
        self.assertIn("**U** = A 与候选臂同起点前五名的并集", workflow)
        self.assertIn("记为**去赢家全面优秀**", workflow)
        self.assertIn("该判定不构成采纳，也不放宽第 2 款的门槛", workflow)
        self.assertIn("长跑锚点、年均换手与集中度表不计入", workflow)
        self.assertIn("年均换手（参考项，不进第 4 款判定）", workflow)
        self.assertTrue((ROOT / "scripts/experimental/ex_winner_symmetry.py").exists())
        self.assertIn("`data/processed/a_share_daily_states_hold.csv`（持仓侧，`--hold-states`", workflow)
        self.assertIn("`data/processed/a_share_pool_model_bands_hold.csv`", workflow)
        self.assertIn(f"| 涨幅减持 | 收盘较持仓均价涨幅 `≥ {daily_scan.SEC93_GAIN_SELL:.0%}`（收盘 ≥ 均价 × {1 + daily_scan.SEC93_GAIN_SELL:.2f}），减一档，不看走势", workflow)
        self.assertIn(f"至少低 `{daily_scan.SEC93_SWAP_MARGIN:.2f}`", workflow)
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
