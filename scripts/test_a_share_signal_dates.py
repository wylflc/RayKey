#!/usr/bin/env python3
"""Signal/evidence date mapping regression tests."""

from __future__ import annotations

import unittest
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from a_share_signal_dates import evidence_date_for_signal, evidence_iso_for_signal, next_workday


class SignalEvidenceDateTest(unittest.TestCase):
    def test_next_weekday(self) -> None:
        self.assertEqual(evidence_iso_for_signal("2026-08-26"), "2026-08-27")

    def test_weekend_is_skipped(self) -> None:
        self.assertEqual(evidence_iso_for_signal("2026-08-28"), "2026-08-31")

    def test_date_input(self) -> None:
        self.assertEqual(evidence_date_for_signal(date(2026, 8, 26)), date(2026, 8, 27))
        self.assertEqual(next_workday(date(2026, 8, 29)), date(2026, 8, 31))


if __name__ == "__main__":
    unittest.main()
