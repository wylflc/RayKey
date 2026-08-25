#!/usr/bin/env python3
"""Regression tests for valuation-card quote dating."""

from __future__ import annotations

import unittest

import apply_valuation_band_cards as app


class QuoteDateTest(unittest.TestCase):
    def test_uses_provider_trade_date(self) -> None:
        self.assertEqual(app.quote_date("20260825161500", "2026-08-26"), "2026-08-25")

    def test_falls_back_when_provider_time_is_missing(self) -> None:
        self.assertEqual(app.quote_date("", "2026-08-26"), "2026-08-26")

    def test_falls_back_when_provider_time_is_malformed(self) -> None:
        self.assertEqual(app.quote_date("2026-08-25", "2026-08-26"), "2026-08-26")


if __name__ == "__main__":
    unittest.main()
