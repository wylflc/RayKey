#!/usr/bin/env python3
"""v4.215（OI-207 H2）：银行股利尺度 × DDM 排序的唯一实现 `bank_valuation`。"""
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
        self.assertAlmostEqual(v, pv + roe_t * bv_n * 0.3 / (0.10 - g_t) / 1.1 ** 10)

    def test_ddm_rejects_no_payout(self):
        self.assertIsNone(bv.ddm_value(10.0, 0.15, 0.0, 0.10))

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


if __name__ == "__main__":
    unittest.main()
