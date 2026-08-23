#!/usr/bin/env python3
"""§6.5.1「每股锚的股本口径」（v4.59，OI-086/OI-087）的回归测试。

Run: ``python3 scripts/test_equity_anchor.py``

锁住四件事：
1. 增发是「股权换现金」：每股 NOPAT 锚不得被募资抬高，募资按面值进每股净现金（东鹏 2026Q1 判例的抽象）；
2. 回购注销同式、符号相反；
3. 东财按后来的送转重述历史 EPS 而不重述 BPS 时，不得把重述误判成股数变化；
4. 送转落在报告期末与公告日之间时，BPS 是否已按除权后股本列示要按数据判、不按公告日假定（比亚迪 2025 中报判例）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_historical_valuation_bands as B  # noqa: E402


def row(period, notice, bps, np_, eps):
    # EPS 按东财 4 位小数列示（精度守卫要求舍入误差 ≤2%）
    return {"report_date": period, "notice_date": notice, "bps": f"{bps}",
            "parent_netprofit": f"{np_}", "basic_eps": f"{eps:.4f}", "security_name": "T"}


class Year:
    def __init__(self, period, notice, equity, np_, tci=None):
        self.period, self.notice_date, self.parent_equity = period, notice, equity
        self.parent_netprofit, self.parent_tci = np_, tci


class ExternalEquityIntraTest(unittest.TestCase):
    """基准公司：年报权益 100 亿、10 亿股（BPS 10）、半年归母净利 8 亿，年中派 0.2 元/股。"""

    def setUp(self):
        self.actions = [{"ex_dividend_date": "2025-06-20", "cash_per_share": "0.2", "share_ratio": "0"}]
        self.ref = row("2024-12-31", "2025-03-30", 10.0, 12e8, 1.2)

    def test_no_external_equity_is_zero(self):
        # 期末权益 = 100 + 8 − 2 = 106 亿，股数不变 → BPS 10.6；x 必须 ≈ 0、股数走 shares_ref
        series = {"2024-12-31": self.ref, "2025-06-30": row("2025-06-30", "2025-08-25", 10.6, 8e8, 0.8)}
        x, shares, basis, mode = B.external_equity_intra(series, self.actions, "2025-06-30", "2024-12-31", 100e8)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(shares, 10e8)
        self.assertEqual(mode, "shares_ref")
        self.assertEqual(basis, "2025-08-25")

    def test_issuance_is_cash_not_operating_book(self):
        # 年初增发 2 亿股、每股 30 元募 60 亿：权益 100+60+8−2.4 = 165.6 亿 / 12 亿股 = BPS 13.8；H1 加权股数 ≈ 12 亿 → EPS 0.667
        series = {"2024-12-31": self.ref, "2025-06-30": row("2025-06-30", "2025-08-25", 165.6e8 / 12e8, 8e8, 8e8 / 12e8)}
        x, shares, _b, mode = B.external_equity_intra(series, self.actions, "2025-06-30", "2024-12-31", 100e8)
        self.assertEqual(mode, "shares_eps")
        self.assertAlmostEqual(shares, 12e8, delta=1e5)   # EPS 四位小数的舍入
        # 募资 60 亿 ÷ 12 亿股 = 5.0 元/股进现金；经营账面 = 13.8 − 5.0 = 8.8 = (100+8−2.4)/12
        self.assertAlmostEqual(x, 60e8 / 12e8, places=3)
        self.assertAlmostEqual(165.6e8 / 12e8 - x, (100e8 + 8e8 - 0.2 * 12e8) / 12e8, places=3)

    def test_buyback_cancellation_is_symmetric(self):
        # 年初回购注销 0.4 亿股、每股 30 元花 12 亿：权益 100+8−1.92−12 = 94.08 亿 / 9.6 亿股 = BPS 9.8；EPS 8/9.6
        series = {"2024-12-31": self.ref, "2025-06-30": row("2025-06-30", "2025-08-25", 94.08e8 / 9.6e8, 8e8, 8e8 / 9.6e8)}
        x, shares, _b, mode = B.external_equity_intra(series, self.actions, "2025-06-30", "2024-12-31", 100e8)
        self.assertEqual(mode, "shares_eps")
        self.assertAlmostEqual(shares, 9.6e8, delta=1e5)
        self.assertAlmostEqual(x, -12e8 / 9.6e8, places=3)       # 现金流出按面值、符号为负
        self.assertAlmostEqual(94.08e8 / 9.6e8 - x, (100e8 + 8e8 - 0.2 * 9.6e8) / 9.6e8, places=3)  # 经营账面按注销后股数

    def test_implausible_negative_is_not_trusted(self):
        # 一个季度内「流出」超过四分之一账面（主体重述／数据错位的典型）→ 不调整并留痕
        series = {"2024-12-31": self.ref, "2025-06-30": row("2025-06-30", "2025-08-25", 76.2e8 / 9e8, 8e8, 8e8 / 9e8)}
        x, _s, _b, mode = B.external_equity_intra(series, self.actions, "2025-06-30", "2024-12-31", 100e8)
        self.assertEqual((x, mode), (0.0, "x_implausible_negative"))

    def test_restated_annual_bps_is_folded_back(self):
        # 年报行 BPS 被东财按后来的 10 转 20 折到 1/3（海螺水泥 2009 判例）：上一行 Q3 BPS 15.9 → 年报 5.43
        actions = [{"ex_dividend_date": "2010-06-21", "cash_per_share": "0.35", "share_ratio": "1.0"},
                   {"ex_dividend_date": "2011-06-10", "cash_per_share": "0.3", "share_ratio": "0.5"}]
        series = {"2009-09-30": row("2009-09-30", "2009-10-28", 15.9, 20e8, 1.13),
                  "2009-12-31": row("2009-12-31", "2010-04-30", 5.43, 35e8, 1.98)}
        self.assertAlmostEqual(B.bps_restated_factor(series, "2009-12-31", actions), 3.0)
        self.assertAlmostEqual(B.effective_bps(series, "2009-12-31", actions), 16.29)
        self.assertAlmostEqual(B.shares_at_period_end(series, actions, "2009-12-31", 287.6e8), 287.6e8 / 16.29)

    def test_restated_eps_is_not_a_share_change(self):
        # 年报行 EPS 被后来的 10 转 10 重述（1.2 → 0.6）而 BPS 未重述；本期 EPS 同样重述：股数倍数 = 1 → shares_ref
        ref = row("2024-12-31", "2025-03-30", 10.0, 12e8, 0.6)
        actions = self.actions + [{"ex_dividend_date": "2025-09-10", "cash_per_share": "0", "share_ratio": "1.0"}]
        series = {"2024-12-31": ref, "2025-06-30": row("2025-06-30", "2025-08-25", 10.6, 8e8, 0.4)}
        x, shares, _b, mode = B.external_equity_intra(series, actions, "2025-06-30", "2024-12-31", 100e8)
        self.assertEqual(mode, "shares_ref")
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(shares, 10e8)

    def test_annual_row_is_zero_by_construction(self):
        series = {"2024-12-31": self.ref}
        x, shares, _b, mode = B.external_equity_intra(series, self.actions, "2024-12-31", "2024-12-31", 100e8)
        self.assertEqual((x, mode), (0.0, "annual_row"))
        self.assertAlmostEqual(shares, 10e8)


class AnnualExternalEquityTest(unittest.TestCase):
    def test_ipo_year_counted_small_residual_ignored(self):
        actions = [{"ex_dividend_date": "2023-06-15", "cash_per_share": "0.5", "share_ratio": "0"}]
        series = {"2021-12-31": row("2021-12-31", "2022-04-20", 5.0, 4e8, 1.0),
                  "2022-12-31": row("2022-12-31", "2023-04-20", 10.0, 6e8, 1.0),   # IPO：股数 4 → 6 亿、权益 20 → 60
                  "2023-12-31": row("2023-12-31", "2024-04-20", 10.5, 7e8, 1.1667)}
        hist = [Year("2021-12-31", "2022-04-20", 20e8, 4e8), Year("2022-12-31", "2023-04-20", 60e8, 6e8),
                Year("2023-12-31", "2024-04-20", 63.3e8, 7e8)]   # 2023：60 + 7 − 3（0.5×6 亿）− 0.7 残差（1.2%）
        xcum, note, brk = B.annual_external_equity(hist, series, actions)
        self.assertIsNone(brk)                                                  # 募资 34 亿 / 账面 60 亿：经营账面 43% > 20%，无断点
        self.assertAlmostEqual(xcum["2021-12-31"], 0.0)
        self.assertAlmostEqual(xcum["2022-12-31"], 60e8 - 20e8 - 6e8, delta=1)   # IPO 募资 34 亿计入
        self.assertAlmostEqual(xcum["2023-12-31"], xcum["2022-12-31"], delta=1)  # −0.7 亿（1.2%）低于 5% 阈值不计
        self.assertEqual(note, "")

    def test_restructuring_breaks_the_window(self):
        # 盐湖式：权益打穿为负、次年债转股 300 亿注资 → 经营账面不可辨，比率窗口自注资年重起
        series = {"2018-12-31": row("2018-12-31", "2019-04-20", 5.47, -34e8, -1.2),
                  "2019-12-31": row("2019-12-31", "2020-04-20", -10.95, -458e8, -16.0),
                  "2020-12-31": row("2020-12-31", "2021-04-20", 0.76, 20e8, 0.37),
                  "2021-12-31": row("2021-12-31", "2022-04-20", 1.72, 45e8, 0.83)}
        hist = [Year("2018-12-31", "2019-04-20", 167e8, -34e8), Year("2019-12-31", "2020-04-20", -305e8, -458e8),
                Year("2020-12-31", "2021-04-20", 41e8, 20e8), Year("2021-12-31", "2022-04-20", 93e8, 45e8)]
        xcum, note, brk = B.annual_external_equity(hist, series, [])
        self.assertEqual(brk, "2020-12-31")                   # 2019 权益为负断一次、2020 注资 326 亿 > 账面再断一次
        self.assertAlmostEqual(xcum["2020-12-31"], 0.0)       # 断点年重起
        self.assertAlmostEqual(xcum["2021-12-31"], 93e8 - 41e8 - 45e8, delta=1)   # 2021：7 亿（17% > 5%）计入
        self.assertIn("book_break", note)


class BasisDateTest(unittest.TestCase):
    def test_pre_and_post_basis(self):
        # 10 转 10 于 07-29 除权、中报 08-30 披露：BPS 仍 69（期末口径）→ 基准 = 期末；若已减半 → 基准 = 公告日
        actions = [{"ex_dividend_date": "2025-07-29", "cash_per_share": "0.4", "share_ratio": "1.0"}]
        q1 = row("2025-03-31", "2025-04-26", 71.0, 9e9, 3.1)
        pre = {"2025-03-31": dict(q1), "2025-06-30": row("2025-06-30", "2025-08-30", 69.0, 15e9, 1.7)}
        post = {"2025-03-31": dict(q1), "2025-06-30": row("2025-06-30", "2025-08-30", 34.8, 15e9, 1.7)}
        self.assertEqual(B.row_basis_date(pre, "2025-06-30", actions), "2025-06-30")
        self.assertEqual(B.row_basis_date(post, "2025-06-30", actions), "2025-08-30")
        self.assertEqual(B.row_basis_date(pre, "2025-03-31", actions), "2025-04-26")   # 窗口无送转 → 公告日
        # 逐日展开：期末口径的带在除权日后须按 split_since=期末 折半，现金仍自公告日起算
        (v,), factor, cash = B.exright_adjust(actions, "2025-08-30", "2025-09-30", (138.0,), split_since="2025-06-30")
        self.assertAlmostEqual(v, 69.0)
        self.assertAlmostEqual(factor, 2.0)
        self.assertAlmostEqual(cash, 0.0)           # 07-29 ≤ 公告日：分红已计入应付股利，不再扣
        (v2,), factor2, _c = B.exright_adjust(actions, "2025-08-30", "2025-09-30", (138.0,))
        self.assertAlmostEqual(v2, 138.0)           # 旧口径（缺省 split_since=公告日）不折——这正是 OI-087 的缺陷
        self.assertAlmostEqual(factor2, 1.0)


if __name__ == "__main__":
    unittest.main()
