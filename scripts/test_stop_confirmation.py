#!/usr/bin/env python3
"""Unit checks for fixed-stop confirmation and deep-breach bypass semantics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_valuation_strategy import update_stop_breach


class StopConfirmationTest(unittest.TestCase):
    def test_default_matches_first_close_below_stop(self) -> None:
        self.assertEqual(update_stop_breach(99.0, 100.0, 0), (1, "confirmed"))
        self.assertEqual(update_stop_breach(100.0, 100.0, 2), (0, ""))

    def test_consecutive_days_reset_when_price_recovers(self) -> None:
        streak, trigger = update_stop_breach(99.0, 100.0, 0, confirm_days=3)
        self.assertEqual((streak, trigger), (1, ""))
        streak, trigger = update_stop_breach(98.0, 100.0, streak, confirm_days=3)
        self.assertEqual((streak, trigger), (2, ""))
        streak, trigger = update_stop_breach(100.5, 100.0, streak, confirm_days=3)
        self.assertEqual((streak, trigger), (0, ""))
        streak, trigger = update_stop_breach(97.0, 100.0, streak, confirm_days=3)
        self.assertEqual((streak, trigger), (1, ""))

    def test_deep_breach_bypasses_confirmation_wait(self) -> None:
        self.assertEqual(
            update_stop_breach(96.9, 100.0, 0, confirm_days=5, deep_pct=0.03),
            (1, "deep"),
        )
        self.assertEqual(
            update_stop_breach(97.5, 100.0, 0, confirm_days=5, deep_pct=0.03),
            (1, ""),
        )

    def test_confirmation_fires_without_deep_breach(self) -> None:
        streak = 0
        for expected in (1, 2):
            streak, trigger = update_stop_breach(99.5, 100.0, streak, confirm_days=3, deep_pct=0.03)
            self.assertEqual((streak, trigger), (expected, ""))
        self.assertEqual(
            update_stop_breach(99.5, 100.0, streak, confirm_days=3, deep_pct=0.03),
            (3, "confirmed"),
        )


if __name__ == "__main__":
    unittest.main()
