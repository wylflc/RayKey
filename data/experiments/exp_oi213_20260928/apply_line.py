"""v4.216：按 §12.1 对齐容差把买入线 1.0495 重解为 1.0034（OI-213 研发资本化上原线合格面 19.698% 超出容差，对齐解合格面 17.777%）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EDITS = {
    'scripts/screen_daily_volume_price_signals.py': [(
        "SEC93_BUY_LINE = 1.0495        # §9.3.1 买入线（对齐解、保留四位小数；在册合格面 17.777%，v4.215 OI-207 银行 H2 上原线 1.0670 合格面 18.393% 超出 §12.1 容差 0.2pp 而重解，回测日志 §12.274）",
        "SEC93_BUY_LINE = 1.0034        # §9.3.1 买入线（对齐解、保留四位小数；在册合格面 17.777%，v4.216 OI-213 研发资本化上原线 1.0495 合格面 19.698% 超出 §12.1 容差 0.2pp 而重解，回测日志 §12.278）")],
    'scripts/sweep_backtest_configs.py': [(
        '    "--width -0.0495 --swap-margin 0.15 "',
        '    "--width -0.0034 --swap-margin 0.15 "'), (
        "    # **v4.215 买入线 1.0495（OI-207 银行 H2，用户 2026-09-28 裁定按 §12.1 重解）**：原线 1.0670 合格面 18.393%，\n    # 与在册 17.777% 差 0.62pp 超出容差，重解到 17.777%（v4.210 由 0.9524 重解到 1.0670 见 §12.266）。",
        "    # **v4.216 买入线 1.0034（OI-213 研发资本化，用户 2026-09-28 按机制正确性采纳）**：原线 1.0495 合格面 19.698%，\n    # 与在册 17.777% 差 1.92pp 超出容差，重解到 17.777%（v4.215 由 1.0670 重解到 1.0495 见 §12.274）。")],
    'scripts/test_strategy_parameter_sync.py': [(
        "        # 候选侧买入线 1.0495（v4.215 OI-207 银行 H2 上重解，§12.274）；换仓边际 0.15（v4.133，§12.174 表 R／§12.176）\n        self.assertEqual(daily_scan.SEC93_BUY_LINE, 1.0495)",
        "        # 候选侧买入线 1.0034（v4.216 OI-213 研发资本化上重解，§12.278）；换仓边际 0.15（v4.133，§12.174 表 R／§12.176）\n        self.assertEqual(daily_scan.SEC93_BUY_LINE, 1.0034)")],
    'docs/000_Ashare_workflow.md': [("| 买入线 | `P/V ≤ 1.0495` |", "| 买入线 | `P/V ≤ 1.0034` |")],
}


def main():
    for rel, pairs in EDITS.items():
        p = ROOT / rel
        t = p.read_text(encoding='utf-8')
        for a, b in pairs:
            assert t.count(a) == 1, (rel, a[:60])
            t = t.replace(a, b)
        p.write_text(t, encoding='utf-8')
        print('edited', rel)


if __name__ == '__main__':
    main()
