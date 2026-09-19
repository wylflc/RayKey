#!/usr/bin/env python3
"""§10.3 策略列核对（strategy_return_tracker.check_rows）与 §9.1 verify 接入（daily_execution_guard.verify_strategy_columns）。"""
import csv
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy_return_tracker as tracker  # noqa: E402
import daily_execution_guard as guard  # noqa: E402

FIELDS = ["as_of", "net_assets_cny", "external_cash_flow_cny", "net_assets_before_flow_cny",
          "strategy_base_net_assets_cny", "strategy_nav_basis", "strategy_unit_nav",
          "strategy_return_pct", "account_peak_net_assets_cny", "drawdown_from_peak_pct", "strategy_epoch"]


def rows(filled=True):
    base = [{"as_of": "2026-08-28", "net_assets_cny": "1000000", "external_cash_flow_cny": "0", "strategy_base_net_assets_cny": "1000000"},
            {"as_of": "2026-08-31", "net_assets_cny": "1010000", "external_cash_flow_cny": "0", "strategy_base_net_assets_cny": ""}]
    for row in base:
        for col in FIELDS:
            row.setdefault(col, "")
    if filled:
        for row, values in zip(base, tracker.compute(base)):
            row.update(values)
    return base


class CheckRows(unittest.TestCase):
    def test_consistent_rows_pass(self):
        self.assertEqual(tracker.check_rows(rows(), require_filled=True), [])

    def test_mismatch_and_missing_are_reported(self):
        data = rows()
        data[1]["strategy_return_pct"] = "9.99"
        self.assertEqual(len(tracker.check_rows(data)), 1)
        blank = rows(filled=False)
        self.assertEqual(tracker.check_rows(blank), [])                       # --check 语义：空列不算不一致
        self.assertTrue(tracker.check_rows(blank, require_filled=True))       # verify 语义：空列即失败

    def test_upto_limits_scope(self):
        data = rows()
        data[1]["strategy_unit_nav"] = "0.5"
        self.assertEqual(tracker.check_rows(data, upto="2026-08-28"), [])
        self.assertEqual(len(tracker.check_rows(data, upto="2026-08-31")), 1)


class GuardVerify(unittest.TestCase):
    def _snapshot(self, data):
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_verify_requires_signal_day_row_and_filled_columns(self):
        guard.verify_strategy_columns("2026-08-31", self._snapshot(rows()))
        with self.assertRaises(ValueError):
            guard.verify_strategy_columns("2026-09-01", self._snapshot(rows()))
        with self.assertRaises(ValueError):
            guard.verify_strategy_columns("2026-08-31", self._snapshot(rows(filled=False)))


if __name__ == "__main__":
    unittest.main()
