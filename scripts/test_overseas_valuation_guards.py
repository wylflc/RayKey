#!/usr/bin/env python3
"""SEC expense signs and overseas thin-equity rejection regressions (§6.8)."""
from __future__ import annotations

import contextlib
import csv
import io
import itertools
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_a_share_core_valuation_pool as pool
import build_overseas_roic_bands as bands
import fetch_overseas_statements as statements


def sec_fixture(signs=(1, 1, 1), ifrs=False):
    maps = statements.IFRS if ifrs else statements.GAAP
    facts = {}

    def duration(key, annual, current, previous):
        facts[maps[key][0]] = {"units": {"shares" if key == "shares" else "USD": [
            dict(start="2024-09-29", end="2025-09-27", filed="2025-11-13",
                 fp="FY", form="20-F" if ifrs else "10-K", val=annual),
            dict(start="2025-09-28", end="2026-06-27", filed="2026-08-05",
                 fp="Q3", form="10-Q", val=current),
            dict(start="2024-09-29", end="2025-06-28", filed="2026-08-05",
                 fp="Q3", form="10-Q", val=previous),
        ]}}

    duration("revenue", 94425, 76397, 71961)
    duration("pretax", 12003, 10705, 9958)
    duration("income_tax", -1428, 2912, -2030)
    duration("interest_expense", 1812 * signs[0], 1379 * signs[1], 1396 * signs[2])
    duration("shares", 1811, 1769, 1812)
    for key, amount in (("total_equity", 116842), ("parent_equity", 110032)):
        facts[maps[key][0]] = {"units": {"USD": [
            dict(end="2025-09-27", filed="2025-11-13", fp="FY",
                 form="20-F" if ifrs else "10-K", val=amount),
            dict(end="2026-06-27", filed="2026-08-05", fp="Q3", form="10-Q", val=amount),
        ]}}
    return {"facts": {"ifrs-full" if ifrs else "us-gaap": facts}}, facts, maps


class SecExpenseSignsTest(unittest.TestCase):
    def test_all_period_sign_combinations_produce_same_annual_and_ttm(self):
        positive_annual = positive_ttm = None
        for signs in itertools.product((1, -1), repeat=3):
            with self.subTest(signs=signs):
                payload, facts, maps = sec_fixture(signs)
                annual = statements.sec_extract("TEST", "Test", payload)
                current = statements.sec_current_extract("TEST", "Test", facts, maps, annual)
                self.assertIsNotNone(current)
                self.assertEqual(annual[0]["interest_expense"], 1812)
                self.assertEqual(annual[0]["ebit"], 13815)
                self.assertEqual(annual[0]["income_tax"], -1428)
                self.assertEqual(current["interest_expense"], 1795)
                self.assertEqual(current["ebit"], 14545)
                self.assertEqual(current["income_tax"], 3514)
                self.assertAlmostEqual(current["nopat"], 14545 * (1 - 3514 / 12750))
                if positive_annual is None:
                    positive_annual, positive_ttm = annual, current
                else:
                    self.assertEqual(annual, positive_annual)
                    self.assertEqual(current, positive_ttm)

    def test_ifrs_finance_costs_and_tax_benefit_keep_distinct_semantics(self):
        payload, _, _ = sec_fixture((-1, 1, -1), ifrs=True)
        annual = statements.sec_extract("TEST", "Test", payload)[0]
        self.assertEqual(annual["interest_expense"], 1812)
        self.assertEqual(annual["income_tax"], -1428)
        self.assertEqual(annual["nopat"], 13815)

    def test_negative_annual_argument_normalized_before_ttm(self):
        payload, facts, maps = sec_fixture()
        annual = statements.sec_extract("TEST", "Test", payload)
        annual[0]["interest_expense"] = -1812
        current = statements.sec_current_extract("TEST", "Test", facts, maps, annual)
        self.assertEqual(current["interest_expense"], 1795)


def model_years(debt, minority=0, nopat=10):
    years = []
    for fiscal in (2023, 2024, 2025):
        year = bands.roic_inputs.RoicYear(period=f"{fiscal}-12-31", notice_date=f"{fiscal+1}-02-01")
        year.revenue, year.ebit, year.nopat = 1000, nopat, nopat
        year.tax_rate, year.tax_rate_observed = 0, True
        year.parent_equity, year.total_equity, year.minority_equity = 100, 100 + minority, minority
        year.interest_debt, year.excess_cash, year.invested_capital = debt, 0, 100 + minority + debt
        year.capex, year.dep_amort, year.cfo = 0, 0, nopat
        year.interest_expense, year.shares = 1, 1
        year.parent_netprofit = 0  # Constant equity: no external equity adjustment in this fixture.
        years.append(year)
    return years


class ThinEquityTest(unittest.TestCase):
    inputs = {"rf_usd": 0.04, "erp_us": 0.05}

    def evaluate(self, path, debt, minority=0, nopat=10):
        with mock.patch.object(bands.roic_inputs, "wacc", return_value=0.1), \
             mock.patch.object(bands.roic_inputs, "normalized_roic", return_value=0.03 if path == "zero_growth" else 0.10), \
             mock.patch.object(bands, "intrinsic_value", return_value=SimpleNamespace(intrinsic_value=nopat / 0.1, terminal_share=0.5)):
            return bands.value_company("TEST", "L2", model_years(debt, minority, nopat), self.inputs)

    def test_exact_boundary_and_both_sides_for_each_path(self):
        for path in ("zero_growth", "growth"):
            for debt, expected in ((49.99, "ok"), (50.0, "rejected"), (50.01, "rejected")):
                with self.subTest(path=path, debt=debt):
                    result = self.evaluate(path, debt)
                    self.assertEqual(result["status"], expected)
                    self.assertEqual(result["path"], path)
                    if expected == "rejected":
                        self.assertIn("薄权益", result["reason"])
                        self.assertNotIn("value", result)

    def test_binding_minority_book_floor_is_a_fixed_claim(self):
        for path in ("zero_growth", "growth"):
            result = self.evaluate(path, 45, minority=5)
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["net_debt_fixed_ps"], 50)

    def test_proportional_minority_is_not_fixed_debt(self):
        for path in ("zero_growth", "growth"):
            result = self.evaluate(path, 100, minority=100, nopat=100)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["net_debt_ps"], 550)
            self.assertEqual(result["net_debt_fixed_ps"], 100)
            self.assertEqual(result["thin_equity_ratio"], 0.1)

    def test_nonpositive_equity_remains_rejected(self):
        for path in ("zero_growth", "growth"):
            result = self.evaluate(path, 110)
            self.assertEqual(result["status"], "rejected")
            self.assertIn("≤ 0", result["reason"])

    def test_missing_current_parent_equity_does_not_fall_back_to_annual(self):
        years = model_years(10)
        current = model_years(10)[-1]
        current.period = "2026-08-31"
        current.total_equity = 150
        current.parent_equity = None
        result = bands.value_company("TEST", "L2", years, self.inputs, current)
        self.assertEqual(result["status"], "rejected")
        self.assertIn("母公司权益不可得", result["reason"])
        self.assertNotIn("非正", result["reason"])
        self.assertNotIn("value", result)

    def test_rejection_clears_stored_band_and_both_reading_views(self):
        for path in ("zero_growth", "growth"):
            rejected = self.evaluate(path, 50)
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                row = dict(security_code="TEST", security_name="Test", market_type="US", currency="USD",
                           quality_tier="L2", attention_class="worth_attention", quality_score="70",
                           fair_price_low="90", fair_price_high="110", band_method="ROIC·增长",
                           band_derivation="roic", valuation_price="120", dossier_dir=str(directory),
                           valuation_reviewed_at="2026-02-01")
                watch = directory / "watch.csv"
                with watch.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(row))
                    writer.writeheader(); writer.writerow(row)
                with mock.patch.object(bands, "WATCHLIST", watch), \
                     mock.patch.object(bands, "load_inputs", return_value=self.inputs), \
                     mock.patch.object(bands, "load_report_evidence", return_value={}), \
                     mock.patch.object(bands, "load_years") as load, \
                     mock.patch.object(bands, "value_company", return_value=rejected), \
                     mock.patch.object(sys, "argv", ["build_overseas_roic_bands.py", "--as-of", "2026-09-10", "--quotes", "skip"]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    load.return_value = {"TEST": []}
                    load.meta, load.current, load.current_meta = {"TEST": {"ccy": "USD"}}, {}, {}
                    self.assertEqual(bands.main(), 0)
                with watch.open() as handle:
                    updated = next(csv.DictReader(handle))
                self.assertEqual(updated["fair_price_low"], "")
                self.assertEqual(updated["fair_price_high"], "")
                self.assertEqual(updated["band_derivation"], "unvaluable")
                self.assertEqual(updated["dossier_status"], "unvaluable_pending_input")
                readme = (directory / "README.md").read_text()
                self.assertIn("薄权益", readme)
                self.assertIn("| 合理价区间 | — ~ — USD |", readme)
                section = pool.build_overseas_section([updated], {})
                rendered = next(line for line in section if line.startswith("| Test |"))
                cells = [s.strip() for s in rendered.split("|")][1:-1]
                self.assertEqual(cells[5:7], ["—", "—"])


if __name__ == "__main__":
    unittest.main()
