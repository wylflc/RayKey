#!/usr/bin/env python3
"""v4.215（OI-207 H2）：银行股利尺度 × DDM 排序的唯一实现 `bank_valuation`；v4.221（OI-230）终值按可持续派息率。"""
import math
import unittest
from unittest.mock import patch

import bank_valuation as bv


class BankValuationTests(unittest.TestCase):
    def test_ddm_matches_closed_form_path(self):
        v = bv.ddm_value(10.0, 0.15, 0.3, 0.10)
        path, roe_t, g_t, bv_n, b = bv.roe_bv_path(10.0, 0.15, 0.3, 0.10)
        self.assertAlmostEqual(roe_t, 0.12)
        self.assertAlmostEqual(g_t, min(0.03, 0.12 * 0.7))
        pv = sum(r * p * 0.3 / 1.1 ** t for t, (r, p) in enumerate(path, 1))
        self.assertAlmostEqual(v, pv + roe_t * bv_n * (1 - g_t / roe_t) / (0.10 - g_t) / 1.1 ** 10)   # 终值可持续派息率

    def test_legacy_terminal_rejects_no_payout(self):
        """v4.221 之前的口径（只供复现旧状态）：终值按当期派息率，不派息不可估。"""
        self.assertIsNone(bv.ddm_value(10.0, 0.15, 0.0, 0.10, sustainable_terminal=False))
        path, roe_t, g_t, bv_n, b = bv.roe_bv_path(10.0, 0.15, 0.3, 0.10)
        pv = sum(r * p * 0.3 / 1.1 ** t for t, (r, p) in enumerate(path, 1))
        self.assertAlmostEqual(bv.ddm_value(10.0, 0.15, 0.3, 0.10, sustainable_terminal=False),
                               pv + roe_t * bv_n * 0.3 / (0.10 - g_t) / 1.1 ** 10)

    def test_ddm_equals_residual_income(self):
        """OI-230：终值派息率 1 − g_T ÷ ROE_T，与同一路径的剩余收益逐位相等（清洁盈余）；派息率为 0 也可估。"""
        for payout in (0.0, 0.1, 0.3):
            path, roe_t, g_t, bv_n, b = bv.roe_bv_path(10.0, 0.15, payout, 0.10)
            ri = 10.0 + sum((r - 0.10) * p / 1.1 ** t for t, (r, p) in enumerate(path, 1)) + (roe_t - 0.10) * bv_n / (0.10 - g_t) / 1.1 ** 10
            self.assertAlmostEqual(bv.ddm_value(10.0, 0.15, payout, 0.10), ri)

    def test_sustainable_terminal_changes_nothing_when_growth_cap_is_slack(self):
        # 派息率 90%：g_T = 12% × 10% = 1.2% < 3%，可持续派息率即当期派息率
        self.assertAlmostEqual(bv.ddm_value(10.0, 0.15, 0.9, 0.10), bv.ddm_value(10.0, 0.15, 0.9, 0.10, sustainable_terminal=False))

    def test_scale_needs_min_banks(self):
        pairs = [(2.0, 1.0)] * (bv.MIN_BANKS - 1)
        self.assertIsNone(bv.h2_scale(pairs))
        self.assertAlmostEqual(bv.h2_scale(pairs + [(2.0, 1.0)]), 2.0)

    def test_scale_is_geometric_mean_and_ignores_invalid(self):
        pairs = [(1.0, 1.0), (4.0, 1.0), (2.0, 1.0), (2.0, 2.0), (8.0, 4.0), (None, 1.0), (3.0, 0.0)]
        expect = math.exp((0 + math.log(4) + math.log(2) + 0 + math.log(2)) / 5)
        self.assertAlmostEqual(bv.h2_scale(pairs), expect)

    def test_level_follows_dividend_model_ranking_follows_ddm(self):
        """H2 的截面几何均值等于 D0 的几何均值；银行之间的比值等于 DDM 的比值。"""
        d0 = {"a": 10.0, "b": 20.0, "c": 5.0, "d": 8.0, "e": 12.0}
        dd = {"a": 6.0, "b": 6.0, "c": 6.0, "d": 3.0, "e": 9.0}
        g = bv.h2_scale((d0[k], dd[k]) for k in d0)
        h2 = {k: dd[k] * g for k in d0}
        geo = lambda xs: math.exp(sum(math.log(x) for x in xs) / len(xs))
        self.assertAlmostEqual(geo(h2.values()), geo(d0.values()))
        self.assertAlmostEqual(h2["e"] / h2["d"], dd["e"] / dd["d"])

    def test_live_h2_falls_back_when_cross_section_small(self):
        with patch.object(bv, "bank_codes", return_value={"600036", "601398"}), \
                patch.object(bv, "BankFundamentals"), patch.object(bv, "ddm_at", return_value=5.0):
            self.assertEqual(bv.live_h2("2026-09-28", lambda c: 10.0, None, {}, None), {})

    def test_live_h2_scales_ddm(self):
        codes = {f"60{i:04d}" for i in range(6)}
        d0 = {c: 10.0 + i for i, c in enumerate(sorted(codes))}
        with patch.object(bv, "bank_codes", return_value=codes), patch.object(bv, "BankFundamentals"), \
                patch.object(bv, "ddm_at", side_effect=lambda fund, acts, c, day: 5.0):
            out = bv.live_h2("2026-09-28", d0.get, None, {}, None)
        g = math.exp(sum(math.log(v / 5.0) for v in d0.values()) / len(d0))
        for c in codes:
            self.assertAlmostEqual(out[c], 5.0 * g * bv.BANK_SCALE)   # OI-227：银行乘同尺系数

    def test_live_h2_values_banks_without_dividend_by_cross_section(self):
        """OI-230：V_D0 不可得而 V_DDM 可估的银行照用当日 G（G 只由两者都可估的银行算出）。"""
        codes = {f"60{i:04d}" for i in range(7)}
        d0 = {c: 10.0 + i for i, c in enumerate(sorted(codes))}
        silent = sorted(codes)[-1]
        d0[silent] = None
        with patch.object(bv, "bank_codes", return_value=codes), patch.object(bv, "BankFundamentals"), \
                patch.object(bv, "ddm_at", side_effect=lambda fund, acts, c, day: 5.0):
            out = bv.live_h2("2026-09-28", d0.get, None, {}, None)
        g = math.exp(sum(math.log(v / 5.0) for v in d0.values() if v) / 6)
        self.assertAlmostEqual(out[silent], 5.0 * g * bv.BANK_SCALE)


if __name__ == "__main__":
    unittest.main()
