"""OI-168: aggregation, classification and point-in-time regression checks."""
from dataclasses import replace
import unittest

from roic_inputs import (
    RoicYear, _year_from_parts, reinvestment_rate, working_capital_inputs, years_before,
)


def balance():
    return {"NOTICE_DATE": "2025-04-01", "INVENTORY": "50",
            "NOTE_ACCOUNTS_RECE": "20", "ACCOUNTS_RECE": "12", "NOTE_RECE": "8",
            "NOTE_ACCOUNTS_PAYABLE": "10", "ACCOUNTS_PAYABLE": "6", "NOTE_PAYABLE": "4",
            "FINANCE_RECE": "5", "TOTAL_EQUITY": "1000", "MONETARYFUNDS": "10"}


class WorkingCapitalTests(unittest.TestCase):
    def test_groups_are_counted_once_and_financing_is_operating(self):
        result = working_capital_inputs(balance())
        self.assertEqual((result.reported, result.operating), (60, 65))
        self.assertEqual((result.receivable_basis, result.payable_basis), ("aggregate", "aggregate"))

    def test_missing_aggregate_uses_components(self):
        row = balance()
        del row["NOTE_ACCOUNTS_RECE"]; del row["NOTE_ACCOUNTS_PAYABLE"]
        result = working_capital_inputs(row)
        self.assertEqual(result.operating, 65)
        self.assertEqual(result.receivable_basis, "components")

    def test_explicit_zero_total_is_not_missing(self):
        row = balance(); row["NOTE_ACCOUNTS_RECE"] = "0"
        result = working_capital_inputs(row)
        self.assertEqual(result.operating, 45)
        self.assertEqual(result.receivable_basis, "aggregate_conflict")

    def test_conflicting_opening_components_do_not_override_year_end(self):
        row = {"NOTE_ACCOUNTS_RECE": "871370660.21", "ACCOUNTS_RECE": "892415771.49",
               "NOTE_RECE": "16910891.14"}
        result = working_capital_inputs(row)
        self.assertEqual(result.operating, 871370660.21)
        self.assertEqual(result.receivable_basis, "aggregate_conflict")

    def test_reclassified_notes_do_not_duplicate_financing_receivables(self):
        row = {"NOTE_ACCOUNTS_RECE": "1002137169.98", "ACCOUNTS_RECE": "1002137169.98",
               "NOTE_RECE": "403462509.22", "FINANCE_RECE": "403462509.22"}
        result = working_capital_inputs(row)
        self.assertAlmostEqual(result.operating, 1405599679.20)
        self.assertEqual(result.receivable_basis, "aggregate_conflict")

    def test_invalid_selected_input_is_unknown(self):
        for field in ("NOTE_ACCOUNTS_RECE", "FINANCE_RECE", "INVENTORY"):
            row = balance(); row[field] = "nan"
            self.assertIsNone(working_capital_inputs(row).operating)
        row = balance(); row["NOTE_RECE"] = "inf"
        result = working_capital_inputs(row)
        self.assertEqual(result.operating, 65)
        self.assertEqual(result.receivable_basis, "aggregate_invalid_components")

    def test_financing_only_changes_working_capital_not_profit_or_capital(self):
        inc = {"NOTICE_DATE": "2025-04-01", "TOTAL_PROFIT": "100", "TOTAL_OPERATE_INCOME": "500"}
        row = balance()
        first = _year_from_parts("T", "2024-12-31", {"balance": row, "income": inc}, False)
        row["FINANCE_RECE"] = "25"
        second = _year_from_parts("T", "2024-12-31", {"balance": row, "income": inc}, False)
        self.assertEqual(second.working_capital_operating - first.working_capital_operating, 20)
        for field in ("nopat", "invested_capital", "interest_debt", "excess_cash", "working_capital", "working_capital_reported"):
            self.assertEqual(getattr(first, field), getattr(second, field), field)

    def test_only_financing_change_enters_reinvestment(self):
        years = [RoicYear(f"{y}-12-31", f"{y+1}-04-01", nopat=100, capex=30,
                          dep_amort=20, working_capital=50) for y in range(2020, 2025)]
        constant = [replace(y, working_capital=y.working_capital + 200) for y in years]
        self.assertEqual(reinvestment_rate(years), reinvestment_rate(constant))
        rising = [replace(y, working_capital=y.working_capital + i*10) for i, y in enumerate(years)]
        self.assertAlmostEqual(reinvestment_rate(rising) - reinvestment_rate(years), .1)

    def test_versions_preserve_their_own_financing_classification(self):
        old = RoicYear("2024-12-31", "2025-04-01", working_capital_operating=65)
        new = replace(old, working_capital_operating=80, superseded=[("2026-04-01", old)])
        keyed = {new.period: new}
        self.assertFalse(years_before(keyed, "2025-03-31", 5))
        self.assertEqual(years_before(keyed, "2026-03-31", 5)[0].working_capital_operating, 65)
        self.assertEqual(years_before(keyed, "2026-04-01", 5)[0].working_capital_operating, 80)


if __name__ == "__main__":
    unittest.main()
