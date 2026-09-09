"""Economic boundary and point-in-time checks for the optional cash constraint."""
import copy
from dataclasses import replace
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_historical_valuation_bands as bands
from intrinsic_value import intrinsic_value, ValuationError
from roic_inputs import RoicYear, maintenance_cash_ratio, years_before, _year_from_parts


def history(net=50):
    return [RoicYear(period=f"{y}-12-31", notice_date=f"{y+1}-04-30",
                     nopat=100, invested_capital=1000, revenue=1000,
                     capex=20+net, dep_amort=20, working_capital=50,
                     cash_inputs_complete=True) for y in range(2020, 2025)]


class MaintenanceProxyTests(unittest.TestCase):
    def test_working_capital_aggregate_or_components(self):
        bal={"NOTICE_DATE":"2025-04-01", "INVENTORY":"50",
             "NOTE_ACCOUNTS_RECE":"20", "ACCOUNTS_RECE":"12", "NOTE_RECE":"8",
             "NOTE_ACCOUNTS_PAYABLE":"10", "ACCOUNTS_PAYABLE":"6", "NOTE_PAYABLE":"4"}
        inc={"NOTICE_DATE":"2025-04-01","TOTAL_PROFIT":"100"}
        y=_year_from_parts("test","2024-12-31",{"balance":bal,"income":inc},False)
        self.assertEqual(y.working_capital,70)  # Preserve the original control.
        self.assertEqual(y.working_capital_reported,60)
        bal.pop("NOTE_ACCOUNTS_RECE");bal.pop("NOTE_ACCOUNTS_PAYABLE")
        y=_year_from_parts("test","2024-12-31",{"balance":bal,"income":inc},False)
        self.assertEqual(y.working_capital_reported,60)

    def test_persistent_fifty_and_ninety(self):
        for net in (50, 90):
            estimate = maintenance_cash_ratio(history(net))
            self.assertEqual(estimate.status, "persistent")
            self.assertAlmostEqual(estimate.ratio, net / 100)

    def test_growth_investment_is_not_maintenance(self):
        years = history(0)
        for i, year in enumerate(years):
            year.revenue = year.invested_capital = 1000 * 1.1 ** i
            year.capex = 20 + (year.revenue - years[i-1].revenue if i else 0)
        self.assertAlmostEqual(maintenance_cash_ratio(years).ratio, 0, places=12)

    def test_fixed_working_capital_is_not_deducted_again(self):
        self.assertEqual(maintenance_cash_ratio(history(0)).ratio, 0)

    def test_recovered_working_capital_offsets_temporary_use(self):
        years = history(0)
        for year, wc in zip(years, [50, 100, 150, 200, 50]):
            year.working_capital = wc
        self.assertEqual(maintenance_cash_ratio(years).ratio, 0)

    def test_one_off_project_does_not_become_permanent_burden(self):
        years = history(0)
        years[2].capex = 1020
        self.assertEqual(maintenance_cash_ratio(years).ratio, 0)

    def test_missing_is_unknown(self):
        years = history()
        years[2].cash_inputs_complete = False
        self.assertIsNone(maintenance_cash_ratio(years).ratio)
        years = history()
        years[2].working_capital = None
        self.assertIsNone(maintenance_cash_ratio(years).ratio)
        years = history()
        years.pop(2)
        self.assertEqual(maintenance_cash_ratio(years).status, "nonconsecutive_years")

    def test_financials_and_acquisitions_are_not_misclassified(self):
        for field, value in [("is_financial", True), ("annualized_months", 6)]:
            years = history()
            setattr(years[2], field, value)
            self.assertIsNone(maintenance_cash_ratio(years).ratio)

    def test_disclosure_and_restatement_versions(self):
        years = history()
        old = copy.deepcopy(years[-1])
        years[-1].capex = 9999
        years[-1].superseded = [("2026-04-30", old)]
        keyed = {y.period: y for y in years}
        self.assertEqual(len(years_before(keyed, "2023-04-29", 5)), 2)
        at = years_before(keyed, "2025-04-30", 5)
        self.assertAlmostEqual(maintenance_cash_ratio(at).ratio, .5)
        self.assertGreater(maintenance_cash_ratio(years_before(keyed, "2026-04-30", 5)).ratio, .5)


class CashValuationTests(unittest.TestCase):
    def test_zero_growth_cash_is_fifty_or_ten(self):
        for burden, cash, value in [(.5, 50, 500), (.9, 10, 100)]:
            result = intrinsic_value(100, .12, 0, .10, roe_terminal=.12,
                                     g_terminal=0, maintenance_ratio=burden)
            self.assertAlmostEqual(result.intrinsic_value, value)
            self.assertTrue(all(abs(e*p-cash)<1e-10 for e,p in zip(result.eps_path,result.payout_path)))

    def test_steady_growth_has_closed_form(self):
        result = intrinsic_value(100, .2, .04, .1, roe_terminal=.2,
                                 g_terminal=.04, maintenance_ratio=.3)
        self.assertAlmostEqual(result.intrinsic_value, 100*1.04*(1-.04/.2-.3)/(.1-.04))

    def test_already_funded_erosion_is_not_deducted_twice(self):
        original = intrinsic_value(100, .3, .04, .1, roe_terminal=.1, g_terminal=.02)
        corrected = intrinsic_value(100, .3, .04, .1, roe_terminal=.1,
                                    g_terminal=.02, maintenance_ratio=.05)
        self.assertAlmostEqual(original.eps_path[0]*original.payout_path[0],
                               corrected.eps_path[0]*corrected.payout_path[0])
        self.assertLess(corrected.intrinsic_value, original.intrinsic_value)

    def test_financing_constraint_reduces_growth(self):
        result = intrinsic_value(100, .12, .25, .1, roe_terminal=.12,
                                 g_terminal=.01, n1=2, maintenance_ratio=.8)
        self.assertGreater(result.clamped_years, 0)
        self.assertLessEqual(result.g_path[0], .12*.2 + 1e-12)
        self.assertGreaterEqual(result.min_payout, -1e-12)

    def test_infeasible_terminal_and_invalid_inputs_reject(self):
        for burden in (.9, 1, -1, float("nan")):
            with self.assertRaises(ValuationError):
                intrinsic_value(100, .12, .03, .1, roe_terminal=.12,
                                g_terminal=.03, maintenance_ratio=burden)

    def test_zero_switch_is_exact(self):
        a = intrinsic_value(100, .3, .04, .1, roe_terminal=.12)
        b = intrinsic_value(100, .3, .04, .1, roe_terminal=.12, maintenance_ratio=0)
        self.assertEqual(a, b)

    def test_higher_burden_does_not_raise_value_at_terminal_boundary(self):
        values=[intrinsic_value(100,.2,.05,.1,roe_terminal=.12,g_terminal=.03,
                                maintenance_ratio=m).intrinsic_value for m in (.70,.73,.74,.749)]
        self.assertEqual(values,sorted(values,reverse=True))
        with self.assertRaises(ValuationError):
            intrinsic_value(100,.2,.05,.1,roe_terminal=.12,g_terminal=.03,maintenance_ratio=.75)

    def test_cash_rejection_invalidates_old_band_until_recovery(self):
        base = bands.Band(code="000001", name="test", report_date="2022-12-31",
                          notice_date="2023-04-01", available_at="2023-04-01", status="ok")
        base.status, base.value, base.band_low, base.band_high = "ok", 10, 9, 11
        blocked = replace(base, report_date="2023-12-31", notice_date="2024-04-01",
                          available_at="2024-04-01", status="rejected", cash_blocked=True)
        recovered = replace(base, report_date="2024-12-31", notice_date="2025-04-01",
                            available_at="2025-04-01")
        prices = [("2022-01-01", 10), ("2023-04-03", 10), ("2024-04-03", 10), ("2025-04-03", 10)]
        with patch.object(bands, "STATE_EFFECTIVE", "notice"):
            rows = bands.daily_states("000001", [base, blocked, recovered], prices, [])
        self.assertEqual([r["date"] for r in rows], ["2023-04-03", "2025-04-03"])


if __name__ == "__main__":
    unittest.main()
