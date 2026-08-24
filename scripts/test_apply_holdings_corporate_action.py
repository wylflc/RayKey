#!/usr/bin/env python3
"""§11.4 持仓除权落地与「已处理」台账的无网络回归。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import apply_holdings_corporate_action as ap


def write_holdings(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ap.HOLDING_FIELDS)
        w.writeheader()
        w.writerow({"security_code": "600036", "security_name": "招商银行", "current_shares": "1000",
                    "cost_basis": "30", "entry_stop_price": "28"})
        w.writerow({"security_code": "000001", "security_name": "平安银行", "current_shares": "500",
                    "cost_basis": "10", "entry_stop_price": ""})


class ApplyCorporateActionTest(unittest.TestCase):
    def test_cash_and_split_adjusts_all_three_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h, ledger = Path(tmp) / "h.csv", Path(tmp) / "ledger.csv"
            write_holdings(h)
            res = ap.apply_action(h, ledger, None, "600036", "2026-07-10", 2.0, 0.5, 0.0, 0.0, True, "test")
            rows = {r["security_code"]: r for r in csv.DictReader(h.open(encoding="utf-8"))}
            self.assertEqual(rows["600036"]["current_shares"], "1500")
            self.assertAlmostEqual(float(rows["600036"]["cost_basis"]), (30 - 2) / 1.5, places=4)
            self.assertAlmostEqual(float(rows["600036"]["entry_stop_price"]), (28 - 2) / 1.5, places=4)
            self.assertEqual(rows["000001"]["current_shares"], "500")          # 其他持仓不动
            led = list(csv.DictReader(ledger.open(encoding="utf-8")))
            self.assertEqual((led[0]["security_code"], led[0]["ex_dividend_date"]), ("600036", "2026-07-10"))
            self.assertEqual(res["shares_after"], "1500")

    def test_rights_subscription_and_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h, ledger = Path(tmp) / "h.csv", Path(tmp) / "ledger.csv"
            write_holdings(h)
            ap.apply_action(h, ledger, None, "600036", "2013-09-05", 0.0, 0.0, 0.174, 9.29, True, "test")
            rows = {r["security_code"]: r for r in csv.DictReader(h.open(encoding="utf-8"))}
            self.assertAlmostEqual(float(rows["600036"]["current_shares"]), 1174.0)
            self.assertAlmostEqual(float(rows["600036"]["cost_basis"]), (30 + 0.174 * 9.29) / 1.174, places=4)
            write_holdings(h)
            ap.apply_action(h, Path(tmp) / "l2.csv", None, "600036", "2013-09-05", 0.0, 0.0, 0.174, 9.29, False, "test")
            rows = {r["security_code"]: r for r in csv.DictReader(h.open(encoding="utf-8"))}
            self.assertEqual(rows["600036"]["current_shares"], "1000")          # 不认购：股数不变，价格口径量仍折算
            self.assertAlmostEqual(float(rows["600036"]["cost_basis"]), (30 + 0.174 * 9.29) / 1.174, places=4)

    def test_duplicate_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h, ledger = Path(tmp) / "h.csv", Path(tmp) / "ledger.csv"
            write_holdings(h)
            ap.apply_action(h, ledger, None, "600036", "2026-07-10", 2.0, 0.0, 0.0, 0.0, True, "test")
            with self.assertRaises(SystemExit):
                ap.apply_action(h, ledger, None, "600036", "2026-07-10", 2.0, 0.0, 0.0, 0.0, True, "test")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            h, ledger = Path(tmp) / "h.csv", Path(tmp) / "ledger.csv"
            write_holdings(h)
            res = ap.apply_action(h, ledger, None, "000001", "2026-07-10", 0.5, 0.0, 0.0, 0.0, True, "test", dry_run=True)
            self.assertEqual(res["cost_after"], "9.5000")
            self.assertEqual(res["stop_after"], "")
            self.assertFalse(ledger.exists())
            rows = {r["security_code"]: r for r in csv.DictReader(h.open(encoding="utf-8"))}
            self.assertEqual(rows["000001"]["cost_basis"], "10")

    def test_event_from_actions_merges_dividend_and_rights_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.csv"
            with a.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=["security_code", "ex_dividend_date", "cash_per_share", "share_ratio",
                                                   "rights_ratio", "rights_price"])
                w.writeheader()
                w.writerow({"security_code": "600036", "ex_dividend_date": "2026-07-10", "cash_per_share": "2", "share_ratio": "0"})
                w.writerow({"security_code": "600036", "ex_dividend_date": "2026-07-10", "cash_per_share": "0", "share_ratio": "0",
                            "rights_ratio": "0.1", "rights_price": "20"})
            ev = ap.event_from_actions(a, "600036", "2026-07-10")
            self.assertEqual(ev, {"cash": 2.0, "ratio": 0.0, "rights_ratio": 0.1, "rights_price": 20.0})
            self.assertIsNone(ap.event_from_actions(a, "600036", "2026-07-11"))


if __name__ == "__main__":
    unittest.main()
