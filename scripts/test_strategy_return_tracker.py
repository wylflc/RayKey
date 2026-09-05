#!/usr/bin/env python3
"""§10.3 策略收益跟踪：时间加权单位净值、现金流口径标识、峰值／回撤与纪元不重置。"""
import unittest

import strategy_return_tracker as tracker


def row(as_of, n, flow="0", base="", pre="", epoch=""):
    return {"as_of": as_of, "net_assets_cny": str(n), "external_cash_flow_cny": flow,
            "strategy_base_net_assets_cny": base, "net_assets_before_flow_cny": pre, "strategy_epoch": epoch}


class StrategyReturnTrackerTest(unittest.TestCase):
    def test_rows_before_base_are_skipped_and_zero_flow_equals_simple_ratio(self):
        rows = [row("2026-08-27", 2811951.90), row("2026-08-28", 2811530.99, base="2811530.99"),
                row("2026-08-31", 2797796.21), row("2026-09-01", 2801094.28)]
        out = tracker.compute(rows)
        self.assertIsNone(out[0])
        self.assertEqual(out[1]["strategy_unit_nav"], "1.000000")
        self.assertEqual(out[2]["strategy_return_pct"], "-0.49")
        self.assertEqual(out[3]["strategy_return_pct"], "-0.37")
        self.assertEqual(out[3]["account_peak_net_assets_cny"], "2811530.99")
        self.assertEqual(out[3]["drawdown_from_peak_pct"], "-0.37")
        self.assertEqual({o["strategy_nav_basis"] for o in out[1:]}, {"exact"})
        self.assertEqual({o["strategy_epoch"] for o in out[1:]}, {"E1"})

    def test_cash_flow_is_time_weighted_not_subtracted_from_principal(self):
        # 初始 100、追加 100 后期末 220：旧式 (220 − 100)/100 − 1 = 20%，TWR 期末近似 = (220 − 100)/100 − 1 → 同为 20%
        # 只在单期内相同；再走一期 +10% 时，旧式 (242 − 100)/100 − 1 = 42%，TWR = 1.2 × 1.1 − 1 = 32%
        rows = [row("d1", 100, base="100"), row("d2", 220, flow="100"), row("d3", 242)]
        out = tracker.compute(rows)
        self.assertEqual(out[1]["strategy_nav_basis"], "eod_approx")
        self.assertEqual(out[1]["strategy_return_pct"], "20.00")
        self.assertEqual(out[2]["strategy_return_pct"], "32.00")
        self.assertEqual(out[2]["account_peak_net_assets_cny"], "132.00")     # 峰值单位净值 1.32 × 基准 100

    def test_pre_flow_valuation_gives_exact_two_subperiod_chain(self):
        # 上一日 100 → 流入前 110（+10%）→ 流入 100 → 期末 231（+10%）：精确 TWR = 1.1 × 1.1 − 1 = 21%
        rows = [row("d1", 100, base="100"), row("d2", 231, flow="100", pre="110")]
        out = tracker.compute(rows)
        self.assertEqual(out[1]["strategy_nav_basis"], "exact")
        self.assertEqual(out[1]["strategy_return_pct"], "21.00")
        # 同样的日终数字没有流前估值：期末近似 (231 − 100)/100 − 1 = 31%，并被标为近似
        approx = tracker.compute([row("d1", 100, base="100"), row("d2", 231, flow="100")])
        self.assertEqual(approx[1]["strategy_nav_basis"], "eod_approx")
        self.assertEqual(approx[1]["strategy_return_pct"], "31.00")

    def test_outflow_and_offsetting_flows(self):
        rows = [row("d1", 100, base="100"), row("d2", 50, flow="-50"), row("d3", 55, flow="0")]
        out = tracker.compute(rows)
        self.assertEqual(out[1]["strategy_return_pct"], "0.00")
        self.assertEqual(out[2]["strategy_return_pct"], "10.00")
        self.assertEqual(out[2]["drawdown_from_peak_pct"], "0.00")

    def test_drawdown_uses_unit_nav_high_water_mark_and_epoch_never_resets(self):
        rows = [row("d1", 100, base="100"), row("d2", 120), row("d3", 90), row("d4", 99)]
        out = tracker.compute(rows, epoch_from=("E2", "d3"))
        self.assertEqual(out[2]["drawdown_from_peak_pct"], "-25.00")
        self.assertEqual(out[3]["drawdown_from_peak_pct"], "-17.50")
        self.assertEqual(out[3]["account_peak_net_assets_cny"], "120.00")
        self.assertEqual([o["strategy_epoch"] for o in out], ["E1", "E1", "E2", "E2"])
        self.assertEqual(out[3]["strategy_unit_nav"], "0.990000")          # 换纪元不清零
        kept = tracker.compute([row("d1", 100, base="100"), row("d2", 120, epoch="E3"), row("d3", 90)])
        self.assertEqual([o["strategy_epoch"] for o in kept], ["E1", "E3", "E3"])

    def test_inconsistent_base_is_rejected(self):
        with self.assertRaises(ValueError):
            tracker.compute([row("d1", 100, base="100"), row("d2", 101, base="99")])
        with self.assertRaises(ValueError):
            tracker.compute([row("d1", 101, base="100")])


if __name__ == "__main__":
    unittest.main()
