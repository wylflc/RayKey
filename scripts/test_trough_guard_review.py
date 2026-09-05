#!/usr/bin/env python3
"""Research orchestration: isolation, independent margins, and registered buy-cap doses."""
import json
from pathlib import Path
import shlex
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "experimental"))
import trough_guard_review as review
import trough_guard_checks as checks


class TroughReviewTests(unittest.TestCase):
    def configs(self, **override):
        manifest = dict(base=review.sweep.BASE, engine_sha256="engine", alignment={"off_line": 1.0757})
        manifest.update(override)
        with patch.object(Path, "read_text", return_value=json.dumps(manifest)), \
                patch.object(review, "sha", return_value="engine"):
            return dict(review.configs())

    def test_registered_arms_and_production_unchanged(self):
        baseline = review.sweep.BASE
        arms = self.configs()
        self.assertEqual(len(arms), 27)
        self.assertEqual(arms["BASE"], "")
        self.assertNotIn("--width", arms["REBUILT_CHECK"])
        self.assertEqual(review.sweep.BASE, baseline)
        self.assertIn("/on/states_cand.csv", arms["REBUILT_CHECK"])

    def test_margin_dose_is_not_scaled_with_alignment(self):
        arms = self.configs()
        for m in range(10, 21):
            label = "OFF" if m == 15 else f"OFF_M{m:02d}"
            args = shlex.split(arms[label])
            self.assertEqual(args[args.index("--swap-margin") + 1], f"{m / 100:.2f}")
            self.assertEqual(args[args.index("--width") + 1], "-0.0757")
            self.assertIn("/off/states_hold.csv", arms[label])

    def test_both_buy_cap_bottoms_and_diagnostic_controls(self):
        arms = self.configs()
        for k in range(1, 7):
            for side in ("ON", "OFF"):
                args = shlex.split(arms[f"{side}_BUY{k}"])
                self.assertEqual(args[args.index("--max-daily-buys") + 1], str(k))
                self.assertNotIn("--swap-margin", args)
        self.assertNotIn("--width", arms["OFF_FIXEDLINE"])
        self.assertIn("--width -0.0757", arms["ON_OFFLINE"])

    def test_stale_base_or_engine_fails_before_sweep(self):
        for override in ({"base": "old baseline"}, {"engine_sha256": "old engine"}):
            with self.subTest(override=override), self.assertRaises(AssertionError):
                self.configs(**override)

    def test_resume_requires_complete_paired_start_sets(self):
        row = {s: {} for s in review.sweep.DEFAULT_STARTS}
        full = {"BASE": dict(row), "OFF": dict(row)}
        ex = {"BASE": dict(row), "OFF": dict(row)}
        with patch.object(Path, "exists", return_value=True), patch.object(checks, "load", return_value=(full, ex, [])):
            self.assertTrue(checks.complete(Path("owned_sweep"), ("BASE", "OFF")))
            ex["OFF"].pop(review.sweep.DEFAULT_STARTS[-1])
            self.assertFalse(checks.complete(Path("owned_sweep"), ("BASE", "OFF")))

    def test_resume_does_not_accept_wrong_arm_set(self):
        row = {s: {} for s in review.sweep.DEFAULT_STARTS}
        wrong = {"BASE": row, "OFF_M13": row}
        with patch.object(Path, "exists", return_value=True), patch.object(checks, "load", return_value=(wrong, wrong, [])):
            self.assertFalse(checks.complete(Path("owned_sweep"), ("BASE", "OFF")))


if __name__ == "__main__":
    unittest.main()
