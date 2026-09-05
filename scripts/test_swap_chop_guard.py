"""Causal, corporate-action and execution checks for research whipsaw guards."""
import unittest
from datetime import date, timedelta

from swap_chop_guard import ChopConfig, ChopGuard
from test_swap_weak_regime import SwapWeakRegimeTest, SWAP_STATES, h_mas


class ChopGuardTest(unittest.TestCase):
    def test_confirmation_cannot_exceed_observed_window(self):
        with self.assertRaises(ValueError):
            ChopConfig("flat", days=21)

    def fixture(self, config=None):
        days = [(date(2024, 1, 1) + timedelta(days=i)).isoformat() for i in range(30)]
        prices = {"H": {d: 99 if i % 2 else 101 for i, d in enumerate(days)}}
        mas = {"H": {d: {20: 100} for d in days}}
        return days, ChopGuard(config or ChopConfig("flat"), prices, mas, {})

    def test_intersection_and_breakdown_escape(self):
        ds, g = self.fixture()
        self.assertTrue(g.blocked("H", ds[-1], 30, None))
        g.prices["H"][ds[-1]] = 97
        self.assertFalse(g.blocked("H", ds[-1], 30, None))
        for d in ds[-3:]:
            g.prices["H"][d] = 99
        self.assertFalse(g.blocked("H", ds[-1], 30, None))

    def test_trending_pullback_is_not_flat_chop(self):
        ds, g = self.fixture()
        g.mas["H"][ds[-6]][20] = 97
        self.assertFalse(g.blocked("H", ds[-1], 30, None))

    def test_no_chop_inference_from_short_history(self):
        ds, g = self.fixture()
        self.assertFalse(g.blocked("H", ds[5], 5, None))

    def test_repeat_initial_netting_progress_expiry_and_reentry(self):
        ds, g = self.fixture(ChopConfig("repeat"))
        lot = object()
        self.assertFalse(g.blocked("H", ds[-1], 30, lot))
        g.record_sale("H", ds[-3], 28, lot, 0)
        self.assertFalse(g.blocked("H", ds[-1], 30, lot))
        g.record_sale("H", ds[-3], 28, lot, 100)
        self.assertTrue(g.blocked("H", ds[-1], 30, lot))
        self.assertFalse(g.blocked("H", ds[-1], 30, object()))
        self.assertFalse(g.blocked("H", ds[-1], 34, lot))
        g.prices["H"][ds[-1]] = 98.4
        self.assertFalse(g.blocked("H", ds[-1], 30, lot))

    def test_action_rebasing_and_no_future_lookahead(self):
        ds, g = self.fixture()
        # 10送10 + 每旧股现金1元：之前的100元均线映射为49.5元。
        g.actions = {"H": {ds[-2]: (1.0, 1.0, 0.0, 0.0), "2099-01-01": (20, 2, 0, 0)}}
        for d in ds[-2:]:
            g.mas["H"][d][20] = 49.5
            g.prices["H"][d] = (g.prices["H"][d] - 1) / 2
        self.assertAlmostEqual(g.features("H", ds[-1])["slope"], 0)
        self.assertTrue(g.blocked("H", ds[-1], 30, None))
        before = g.features("H", ds[-3])
        g.prices["H"][ds[-1]] = 1
        self.assertEqual(before, g.features("H", ds[-3]))
        self.assertEqual(g.rebase("H", 100, ds[0], ds[-1]), 49.5)

    def test_engine_blocks_and_preserves_deep_break(self):
        fixture = SwapWeakRegimeTest()
        # Flat classification requires history; a deep break remains eligible regardless.
        plain = fixture.run_case(SWAP_STATES, fixture.PLAIN_MAS)
        off = fixture.run_case(SWAP_STATES, fixture.PLAIN_MAS, swap_chop=ChopConfig())
        self.assertEqual(plain, off)
        guarded = fixture.run_case(SWAP_STATES, fixture.PLAIN_MAS, swap_chop=ChopConfig("flat"))
        self.assertEqual(guarded["sells"], 1)

    def test_engine_repeat_with_real_net_sales(self):
        from test_swap_weak_regime import row
        ds = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
        states = {d: [row("H", 10, 20 if i < 2 else 8)] +
                  ([row("X", 10, 20)] if i >= 2 else []) +
                  ([row("Y", 10, 20)] if i >= 3 else []) for i, d in enumerate(ds)}
        mas = {"H": h_mas({d: 9 if i < 2 else 10.1 for i, d in enumerate(ds)}),
               "X": {d: {20: 9, 60: 8} for d in ds[2:]},
               "Y": {d: {20: 9, 60: 8} for d in ds[3:]}}
        fixture = SwapWeakRegimeTest()
        g = fixture.run_case(states, mas, x=0.5, net_same_day=True, swap_chop=ChopConfig("repeat", days=4))
        self.assertEqual(g["sells"], 1)
        self.assertEqual(g["stats"]["换仓卖出源·形态复核挡下"], 2)
        g = fixture.run_case(states, mas, x=0.5, net_same_day=True, swap_chop=ChopConfig("repeat", days=3))
        self.assertEqual(g["sells"], 2)  # third consecutive weak signal releases the second tranche


if __name__ == "__main__":
    unittest.main()
