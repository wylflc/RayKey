#!/usr/bin/env python3
"""OI-102 海外财报证据日与季度 TTM 回归测试。

Run: ``python3 scripts/test_overseas_report_evidence.py``
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_overseas_earnings_calendar as calendar  # noqa: E402
import fetch_overseas_statements as statements  # noqa: E402
import build_a_share_core_valuation_pool as core_pool  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _node(entries: list[dict], unit: str = "USD") -> dict:
    return {"units": {unit: entries}}


class SecTtmTest(unittest.TestCase):
    def test_latest_quarter_is_annual_plus_current_less_comparative(self):
        filed = "2026-05-27"

        def duration(cur: float, old: float) -> dict:
            return _node([
                {"start": "2026-01-01", "end": "2026-03-31", "val": cur,
                 "filed": filed, "form": "10-Q", "fp": "Q1"},
                {"start": "2025-01-01", "end": "2025-03-31", "val": old,
                 "filed": filed, "form": "10-Q", "fp": "Q1"},
            ])

        def instant(value: float) -> dict:
            return _node([{"end": "2026-03-31", "val": value, "filed": filed,
                           "form": "10-Q", "fp": "Q1"}])

        tax = {
            "RevenueFromContractWithCustomerExcludingAssessedTax": duration(120, 100),
            "OperatingIncomeLoss": duration(30, 20),
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": duration(32, 22),
            "IncomeTaxExpenseBenefit": duration(8, 5),
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": instant(500),
            "StockholdersEquity": instant(490),
            "MinorityInterest": instant(10),
            "LongTermDebt": instant(40),
            "CashAndCashEquivalentsAtCarryingValue": instant(100),
            "WeightedAverageNumberOfDilutedSharesOutstanding": _node([
                {"start": "2026-01-01", "end": "2026-03-31", "val": 50,
                 "filed": filed, "form": "10-Q", "fp": "Q1"}], "shares"),
        }
        annual = statements._build_row(
            "US", "TEST", "Test", "2025-12-31", "2026-02-01", "USD",
            1000, 200, 220, 50, 0, 480, 470, 10, 35, 90,
            0, 0, 150, 50, {}, "annual fixture", 0.21,
        )
        row = statements.sec_current_extract("TEST", "Test", tax, statements.GAAP, [annual], "2026-05-20")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["period"], "2026-03-31")
        self.assertEqual(row["notice_date"], "2026-05-20")
        self.assertEqual(row["period_type"], "ttm")
        self.assertEqual(row["revenue"], 1020)  # 1000 + 120 - 100
        self.assertEqual(row["pretax"], 230)


class CalendarEvidenceTest(unittest.TestCase):
    def test_expired_expected_date_is_not_disclosure_evidence(self):
        row = {"security_code": "PDD", "security_name": "拼多多", "market_type": "US",
               "valuation_reviewed_at": "2026-05-27", "evidence_available_at": "2026-05-27",
               "last_report_date": "2026-05-27", "next_report_date": "2026-08-24"}
        overdue, missing, _ = calendar.overdue_reviews([row], date(2026, 8, 25))
        self.assertEqual(overdue, [])
        self.assertEqual(missing, [])
        due = calendar.verification_due([row], date(2026, 8, 25))
        self.assertEqual([item["security_code"] for item in due], ["PDD"])

    def test_calendar_apply_does_not_overwrite_official_last_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watch.csv"
            fields = ["security_code", "security_name", "market_type", "last_report_date",
                      "next_report_date", "next_report_source"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"security_code": "PDD", "security_name": "拼多多", "market_type": "US",
                                 "last_report_date": "2026-05-27", "next_report_date": "",
                                 "next_report_source": ""})
            calendar.apply_to_watchlist(path, {"PDD": {"last": "2026-08-24", "next": "2026-11-20"}}, "2026-08-25")
            with path.open(encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["last_report_date"], "2026-05-27")
            self.assertEqual(row["next_report_date"], "2026-11-20")

    def test_overseas_review_log_is_batch_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "log.csv"
            row = {"market_type": "US", "security_code": "PDD", "security_name": "拼多多",
                   "quality_tier": "L2", "strategy_tag": "C-GARP成长型",
                   "valuation_reason": "Q1 evidence", "evidence_sources": "issuer_ir",
                   "valuation_batch_id": "overseas_review_20260825"}
            args = (log, [row], "2026-08-25", Path("watch.csv"), Path("pool.md"))
            core_pool.log_overseas_decisions(*args)
            core_pool.log_overseas_decisions(*args)
            with log.open(encoding="utf-8-sig") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 1)


class MaterializedEvidenceTest(unittest.TestCase):
    def test_watchlist_dates_and_events_equal_official_evidence_ledger(self):
        with (ROOT / "data/reference/overseas_report_evidence.csv").open(encoding="utf-8-sig") as handle:
            evidence = {r["security_code"]: r for r in csv.DictReader(handle)}
        with (ROOT / "data/processed/overseas_watchlist_valuation.csv").open(encoding="utf-8-sig") as handle:
            watch = {r["security_code"]: r for r in csv.DictReader(handle)}
        self.assertEqual(set(evidence), set(watch))
        for code, item in evidence.items():
            self.assertEqual(watch[code]["valuation_reviewed_at"], item["evidence_date"], code)
            self.assertEqual(watch[code]["evidence_available_at"], item["evidence_date"], code)
            self.assertEqual(watch[code]["last_report_date"], item["evidence_date"], code)
            self.assertEqual(watch[code]["valuation_evidence_event"], item["report_event"], code)

    def test_pdd_q2_is_in_ttm_inputs(self):
        with (ROOT / "data/interim/overseas_roic_years.csv").open(encoding="utf-8-sig") as handle:
            rows = [r for r in csv.DictReader(handle)
                    if r["security_code"] == "PDD" and r["period_type"] == "ttm"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["period"], "2026-06-30")
        self.assertEqual(rows[0]["notice_date"], "2026-08-24")
        self.assertEqual(rows[0]["report_label"], "二季报（2026Q2）")

    def test_valuation_path_hides_implementation_notes(self):
        self.assertEqual(core_pool._display_valuation_path("ROIC·增长（§6.5.2.3 同口径）"), "ROIC·增长")
        self.assertEqual(core_pool._display_valuation_path("隐含PB：档案带"), "隐含PB")

    def test_every_supported_latest_interim_report_has_matching_ttm_row(self):
        with (ROOT / "data/reference/overseas_report_evidence.csv").open(encoding="utf-8-sig") as handle:
            evidence = {r["security_code"]: r for r in csv.DictReader(handle)}
        unsupported_or_annual = {"00267", "MSFT", "005930", "000660", "BRK.B", "SPCX"}
        with (ROOT / "data/interim/overseas_roic_years.csv").open(encoding="utf-8-sig") as handle:
            current = {(r["security_code"], r["period"]) for r in csv.DictReader(handle)
                       if r["period_type"] == "ttm"}
        expected = {(code, row["report_period"]) for code, row in evidence.items()
                    if code not in unsupported_or_annual}
        self.assertEqual(current, expected)


class HkInterestDebtTest(unittest.TestCase):
    """OI-133：港股有息负债须计入租赁负债、应付债券与可转换票据。"""

    @staticmethod
    def _tables(period: str, balance: dict[str, float], date_type: str = "001") -> dict[str, list[dict]]:
        def rows(kind: str, items: dict[str, float]) -> list[dict]:
            return [{"REPORT_DATE": f"{period} 00:00:00", "DATE_TYPE_CODE": date_type,
                     "STD_ITEM_NAME": name, "AMOUNT": amount} for name, amount in items.items()]
        income = {"营业额": 1000.0, "经营溢利": 200.0, "除税前溢利": 190.0, "税项": 30.0, "融资成本": 10.0}
        cashflow = {"购建固定资产": -50.0, "加:折旧及摊销": 40.0, "经营业务现金净额": 220.0}
        return {"balance": rows("balance", balance), "income": rows("income", income), "cashflow": rows("cashflow", cashflow)}

    _BALANCE = {"总权益": 900.0, "股东权益": 880.0, "少数股东权益": 20.0, "现金及等价物": 300.0,
                "长期贷款": 100.0, "短期贷款": 20.0, "应付票据(非流动)": 60.0, "应付票据": 5.0,
                "应付债券": 30.0, "可转换票据及债券": 45.0,
                "融资租赁负债(非流动)": 70.0, "融资租赁负债(流动)": 15.0,
                "递延税项负债": 12.0, "合同负债": 33.0, "总负债": 500.0}
    _EXPECTED_DEBT = 100.0 + 20.0 + 60.0 + 5.0 + 30.0 + 45.0 + 70.0 + 15.0

    def test_annual_debt_includes_leases_bonds_and_convertibles(self):
        rows = statements.hk_extract("TEST", "测试", self._tables("2025-12-31", self._BALANCE), 10.0)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["interest_debt"], self._EXPECTED_DEBT)
        for key in ("bonds", "convertibles", "lease_nc", "lease_c"):
            self.assertIn(f"{key}=balance:", rows[0]["tags_used"], key)

    def test_alternate_convertible_label_is_mapped(self):
        balance = dict(self._BALANCE)
        balance["可转换债券及票据"] = balance.pop("可转换票据及债券")
        rows = statements.hk_extract("TEST", "测试", self._tables("2025-12-31", balance), 10.0)
        self.assertAlmostEqual(rows[0]["interest_debt"], self._EXPECTED_DEBT)

    def test_ttm_snapshot_uses_same_debt_keys(self):
        annual_tables = self._tables("2025-12-31", self._BALANCE)
        annual = statements.hk_extract("TEST", "测试", annual_tables, 10.0)[0]
        interim = self._tables("2026-06-30", self._BALANCE, date_type="002")
        previous = self._tables("2025-06-30", self._BALANCE, date_type="002")
        tables = {kind: annual_tables[kind] + interim[kind] + previous[kind] for kind in annual_tables}
        row = statements.hk_current_extract("TEST", "测试", tables, 10.0, [annual], evidence_date="2026-08-27")
        self.assertIsNotNone(row)
        self.assertEqual(row["period"], "2026-06-30")
        self.assertAlmostEqual(row["interest_debt"], self._EXPECTED_DEBT)


class RefreshFallbackTest(unittest.TestCase):
    def test_failed_sec_refresh_keeps_cached_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(statements, "RAW_DIR", Path(tmp)):
            path = Path(tmp) / "sec" / "TEST.json"
            path.parent.mkdir(parents=True)
            payload = {"facts": {}, "padding": "x" * 1100}
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(statements, "_get", side_effect=OSError("offline")):
                self.assertEqual(statements.sec_download("TEST", "0000000001", True), payload)


if __name__ == "__main__":
    unittest.main()
