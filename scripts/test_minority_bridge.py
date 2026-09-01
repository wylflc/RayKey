#!/usr/bin/env python3
"""OI-128 股权桥少数股东口径：份额估计与「账面为下界」的扣减。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import roic_inputs as ri  # noqa: E402


def _year(period, net_profit=None, minority_profit=None,
          minority_equity=0.0, total_equity=None):
    y = ri.RoicYear(period=period, notice_date=period)
    y.net_profit, y.minority_profit = net_profit, minority_profit
    y.minority_equity, y.total_equity = minority_equity, total_equity
    return y


class MinorityShare(unittest.TestCase):
    def test_median_of_earnings_share(self):
        hist = [_year("2023-12-31", 100.0, 40.0), _year("2024-12-31", 100.0, 50.0),
                _year("2025-12-31", 100.0, 60.0)]
        self.assertEqual(ri.minority_share(hist), (0.5, "earnings"))

    def test_loss_year_excluded_not_averaged_in(self):
        """合并净利为负的年份剔除——分母过零时比值发散，中位也救不回来。"""
        hist = [_year("2023-12-31", -10.0, -8.0), _year("2024-12-31", 100.0, 30.0),
                _year("2025-12-31", 100.0, 30.0)]
        share, basis = ri.minority_share(hist)
        self.assertEqual(basis, "earnings")
        self.assertAlmostEqual(share, 0.30)

    def test_negative_minority_clamped_to_zero(self):
        hist = [_year("2024-12-31", 100.0, -20.0), _year("2025-12-31", 100.0, -10.0)]
        self.assertEqual(ri.minority_share(hist), (0.0, "earnings"))

    def test_cap_applies(self):
        hist = [_year("2025-12-31", 100.0, 99.0)]
        self.assertEqual(ri.minority_share(hist), (ri.MINORITY_SHARE_CAP, "earnings"))

    def test_book_fallback_when_no_positive_profit_year(self):
        hist = [_year("2025-12-31", -5.0, -1.0, minority_equity=30.0, total_equity=100.0)]
        self.assertEqual(ri.minority_share(hist), (0.30, "book_fallback"))

    def test_no_equity_gives_zero(self):
        hist = [_year("2025-12-31", None, None, total_equity=0.0)]
        self.assertEqual(ri.minority_share(hist), (0.0, "none"))


class EquityBridge(unittest.TestCase):
    """`build_historical_valuation_bands.equity_bridge` 的口径，就地复算（闭包不可直接导入）。"""

    @staticmethod
    def bridge(ev, fin_nd, book_ps, m, x_ps=0.0, basis="earnings"):
        minority, proportional = book_ps, 0.0
        if basis == "earnings" and m > 0:
            total_eq = ev - fin_nd
            if total_eq > 0 and m * total_eq > book_ps:
                minority = proportional = m * total_eq
        nd = fin_nd + minority - x_ps
        return nd, nd - proportional

    def nd(self, *a, **k):
        return self.bridge(*a, **k)[0]

    def test_book_basis_unchanged(self):
        self.assertAlmostEqual(self.nd(100.0, 10.0, 20.0, 0.5, basis="book"), 30.0)

    def test_earnings_share_binds_when_above_book(self):
        # 权益价值 90，按 50% 分得 45 > 账面 20
        self.assertAlmostEqual(self.nd(100.0, 10.0, 20.0, 0.5), 55.0)

    def test_book_is_a_floor(self):
        # 权益价值 90，按 10% 分得 9 < 账面 20 → 仍扣账面
        self.assertAlmostEqual(self.nd(100.0, 10.0, 20.0, 0.1), 30.0)

    def test_zero_share_keeps_book(self):
        self.assertAlmostEqual(self.nd(100.0, 10.0, 20.0, 0.0), 30.0)

    def test_external_equity_not_shared_with_minority(self):
        self.assertAlmostEqual(self.nd(100.0, 10.0, 20.0, 0.5, x_ps=3.0), 52.0)

    def test_nonpositive_equity_value_falls_back_to_book(self):
        self.assertAlmostEqual(self.nd(10.0, 30.0, 20.0, 0.5), 50.0)


class ThinEquityGuardInput(unittest.TestCase):
    """薄权益守卫只看**不随 EV 缩放**的那部分扣减：按盈利份额分走的一份与 EV 同比例，
    对相对误差无放大作用，计进去会把「比例切分」误判成「杠杆」。"""

    bridge = staticmethod(EquityBridge.bridge)

    def test_proportional_slice_excluded_from_guard(self):
        nd, fixed = self.bridge(100.0, 10.0, 20.0, 0.5)
        self.assertAlmostEqual(nd, 55.0)        # 10 + 45
        self.assertAlmostEqual(fixed, 10.0)     # 只剩净金融负债
        self.assertLess(fixed / 100.0, 0.5)     # 不触发守卫

    def test_book_floor_counts_as_fixed(self):
        nd, fixed = self.bridge(100.0, 10.0, 20.0, 0.1)
        self.assertAlmostEqual(nd, 30.0)
        self.assertAlmostEqual(fixed, 30.0)     # 账面是固定额，全部计入

    def test_book_basis_guard_unchanged(self):
        nd, fixed = self.bridge(100.0, 10.0, 45.0, 0.5, basis="book")
        self.assertAlmostEqual(nd, fixed)       # book 口径下两者恒等，守卫逐位不变

    def test_amplification_matches_fixed_part(self):
        """放大倍数 = EV ÷ 股权价值，只由固定扣减决定。"""
        ev, fin_nd, m = 100.0, 10.0, 0.5
        nd, fixed = self.bridge(ev, fin_nd, 5.0, m)
        value = ev - nd
        bumped = (ev * 1.01) - self.bridge(ev * 1.01, fin_nd, 5.0, m)[0]
        self.assertAlmostEqual((bumped / value - 1) / 0.01, ev / (ev - fixed), places=6)


if __name__ == "__main__":
    unittest.main()
