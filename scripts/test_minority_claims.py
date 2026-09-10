#!/usr/bin/env python3
"""OI-175: accounting identities, event timing and stale-band prevention."""
import contextlib
import argparse
import copy
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import minority_claims as mc
import build_historical_valuation_bands as model
import apply_model_bands_to_dossiers as dossiers
import build_pool_model_bands as pool
import build_hold_model_bands as hold
import build_hold_daily_states as hold_daily
import apply_forecast_band_overlay as overlay
from screen_daily_volume_price_signals import load_model_bands


def fixture():
    return dict(security_code="999999", event_id="test", effective_date="2026-06-30",
                report_date="2026-06-30", known_from="2026-08-29", status="reconciled",
                reason="Synthetic accounting fixture, not a company valuation", sources=["fixture"],
                snapshot=dict(shares=10, total_equity=1000, parent_equity=800,
                              minority_equity=200, reported_debt=350,
                              cash_and_trading_assets=20, annual_revenue=1000,
                              annual_report_date="2025-12-31", annual_net_profit=100,
                              annual_minority_profit=30, ttm_net_profit=120,
                              subjects=[dict(subject="sub", minority_fraction=.2,
                                             fixed_exit_fraction=.2, exit_basis="fixed",
                                             minority_equity=150, redemption_liability=250,
                                             dividend_liability=0, liability_in_reported_debt=250,
                                             annual_net_profit=100, annual_minority_profit=30)]))


def row(code="000938", **changes):
    return dict(dict(security_code=code, security_name="fixture", report_date="2024-06-30",
                     available_at="2024-08-30", notice_date="2024-08-30", status="ok", reason="",
                     intrinsic_value="100", band_low="90", band_high="110", roic_path="growth"),
                **changes)


def write_rows(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)


class Accounting(unittest.TestCase):
    def test_fixed_exit_is_not_also_perpetual_equity(self):
        s = mc.reconcile(fixture())
        self.assertEqual((s.financial_net_debt, s.fixed_claim, s.residual_book, s.residual_share),
                         (100, 250, 50, 0))
        self.assertEqual(mc.equity_bridge(1000, s.financial_net_debt, s.residual_book,
                                         s.residual_share, fixed_claim=s.fixed_claim)[0], 400)

    def test_liability_caption_migration_is_neutral(self):
        a = fixture()
        b = copy.deepcopy(a)
        b["snapshot"]["reported_debt"] -= 250
        b["snapshot"]["subjects"][0]["liability_in_reported_debt"] = 0
        self.assertEqual(mc.reconcile(a), mc.reconcile(b))

    def test_partial_exit_and_ownership_change(self):
        e = fixture()
        e["snapshot"]["subjects"][0]["fixed_exit_fraction"] = .1
        s = mc.reconcile(e)
        self.assertAlmostEqual(s.residual_share, .1)
        self.assertAlmostEqual(s.residual_book, 125)

    def test_ownership_change_without_fixed_claim(self):
        e = fixture()
        e["snapshot"]["subjects"][0].update(fixed_exit_fraction=0, exit_basis="none",
                                          redemption_liability=0, liability_in_reported_debt=0)
        self.assertAlmostEqual(mc.reconcile(e).residual_share, .2)

    def test_dividends_on_continuing_rights_are_floor(self):
        e = fixture()
        e["snapshot"]["subjects"][0].update(fixed_exit_fraction=.1, dividend_liability=20)
        s = mc.reconcile(e)
        self.assertEqual((s.fixed_claim, s.dividend_floor), (260, 10))
        # Ordinary rights are worth 250 here: the dividend floor is not added again.
        self.assertEqual(mc.equity_bridge(2600, 100, 125, .1, fixed_claim=260,
                                         dividend_floor=10)[0], 610)

    def test_incomplete_variable_and_nonfinite_facts_fail(self):
        for mutate in (
            lambda e: e["snapshot"].update(iv=22),
            lambda e: e["snapshot"].update(shares=float("nan")),
            lambda e: e["snapshot"].update(total_equity=998),
            lambda e: e["snapshot"]["subjects"][0].update(exit_basis="future_appraisal"),
            lambda e: e["snapshot"]["subjects"].append(copy.deepcopy(e["snapshot"]["subjects"][0])),
        ):
            e = fixture(); mutate(e)
            with self.assertRaises(ValueError): mc.reconcile(e)

    def test_overlay_uses_the_same_bridge(self):
        b = dict(row("999999"), nopat_ps="10", ev_ps="100", net_debt_ps="40",
                 fin_net_debt_ps="10", minority_book_ps="5", minority_share=".2",
                 minority_fixed_claim_ps="25", minority_dividend_floor_ps="3")
        ev, iv, _ = overlay.recompute(b, 1.2)
        self.assertEqual(iv, ev - mc.equity_bridge(ev, 10, 5, .2, fixed_claim=25, dividend_floor=3)[0])


class Timing(unittest.TestCase):
    def test_registry_disclosure_boundary(self):
        self.assertIsNone(mc.event_as_of("000938", "2024-09-04"))
        self.assertEqual(mc.event_as_of("000938", "2024-09-05")["event_id"], "000938-h3c-2024-closing")
        self.assertEqual(mc.event_as_of("000938", "2026-08-28")["report_date"], "2025-12-31")
        self.assertEqual(mc.event_as_of("000938", "2026-08-29")["report_date"], "2026-06-30")

    def test_current_registry_is_valid(self):
        self.assertEqual(set(mc.load_events()), {"000938"})

    def test_complete_snapshot_does_not_revive_old_same_period_row(self):
        e = fixture()
        with patch.object(mc, "registry", return_value={"999999": [e]}):
            b = row("999999", report_date=e["report_date"], available_at=e["known_from"])
            self.assertTrue(mc.row_blocked(mc.invalidate_row(b, e["known_from"])))
            b.update(minority_claim_event="test", minority_claim_status="reconciled")
            self.assertEqual(mc.invalidate_row(b, e["known_from"]), b)
            self.assertTrue(mc.blocking_reason("999999", "2026-10-30", "2026-09-30"))

    def test_duplicate_version_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"events.json"
            p.write_text(json.dumps(dict(events=[fixture(), fixture()])))
            with self.assertRaises(ValueError): mc.load_events(p)

    def test_daily_cached_band_stops_at_event(self):
        b = model.Band(code="000938", name="fixture", report_date="2024-06-30",
                       notice_date="2024-08-30", available_at="2024-08-30", status="ok",
                       value=100, band_low=90, band_high=110)
        prices = [(d, 80) for d in ("2024-01-01", "2024-09-04", "2024-09-05", "2024-09-06")]
        with patch.object(model, "STATE_EFFECTIVE", "notice"):
            result = model.daily_states("000938", [b], prices, [])
        self.assertEqual([r["date"] for r in result], ["2024-09-04"])


class Readers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bands = self.root / "bands.csv"

    def test_archive_and_scanner_cannot_fall_back(self):
        write_rows(self.bands, [row(), row("300919")])
        before, _ = dossiers.latest_model_bands(self.bands, "2024-01-01", as_of="2024-09-04")
        after, blocked = dossiers.latest_model_bands(self.bands, "2024-01-01", as_of="2026-09-10")
        self.assertIn("000938", before)
        self.assertNotIn("000938", after)
        self.assertTrue(mc.row_blocked(blocked["000938"]))
        write_rows(self.bands, [row(available_at="2025-08-30"), row("300919", available_at="2025-08-30")])
        self.assertEqual(set(load_model_bands(self.bands, "2026-09-10")), {"300919"})

    def test_explicit_rejection_beats_older_ok_without_registry(self):
        b = row("999999", available_at="2026-01-01")
        rejected = dict(b, available_at="2026-08-29", status="rejected", minority_claim_status="blocked",
                        intrinsic_value="", band_low="", band_high="")
        write_rows(self.bands, [b, rejected])
        self.assertNotIn("999999", load_model_bands(self.bands, "2026-09-10"))
        self.assertTrue(mc.row_blocked(hold.select_row(b, rejected, "2026-09-10")[0]))
        self.assertTrue(mc.row_blocked(hold.select_row(rejected, b, "2026-09-10")[0]))

    def test_hold_checks_both_cached_inputs(self):
        b = row()
        self.assertTrue(mc.row_blocked(hold.select_row(b, dict(b, intrinsic_value="200"), "2026-09-10")[0]))
        self.assertEqual(hold.select_row(row("300919"), row("300919", intrinsic_value="200"), "2026-09-10")[1], "b2")

    def test_hold_daily_filters_a_stale_second_input(self):
        write_rows(self.bands, [dict(security_code="000938", date=d, band_report_date="2024-06-30")
                                for d in ("2024-09-04", "2024-09-05")])
        reader = hold_daily.BlockReader(self.bands)
        try:
            _, block = reader.next_block()
            self.assertEqual(len(block), 1)
            self.assertEqual(block[0][1], "2024-09-04")
        finally:
            reader._fh.close()

    def test_pool_cli_checks_old_files(self):
        write_rows(self.bands, [row()])
        members, states, output = [self.root/n for n in ("pool.csv", "states.csv", "out.csv")]
        write_rows(members, [dict(security_code="000938", security_name="fixture")])
        states.write_text("security_code,date,intrinsic_value\n")
        argv = ["pool", "--signal-date", "2026-09-09", "--pool", str(members),
                "--states", str(states), "--bands", str(self.bands), "--out", str(output)]
        with patch("sys.argv", argv), patch.object(pool, "ROOT", self.root), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pool.main(), 0)
        with output.open() as f: result = next(csv.DictReader(f))
        self.assertEqual((result["status"], result["intrinsic_value"]), ("rejected", ""))

    def test_forecast_cli_cannot_resurrect_blocked_band(self):
        write_rows(self.bands, [row()])
        argv = ["overlay", "--signal-date", "2026-09-09", "--bands", str(self.bands)]
        for option in ("forecasts", "disclosures", "pool", "corporate-actions"):
            argv.extend(["--"+option, str(self.root/"missing.csv")])
        with patch("sys.argv", argv), patch.object(overlay, "load_financials", return_value={}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(overlay.main(), 0)
        with self.bands.open(encoding="utf-8-sig") as f: result = next(csv.DictReader(f))
        self.assertEqual((result["status"], result["intrinsic_value"]), ("rejected", ""))


class CompleteModel(unittest.TestCase):
    """Replay the actual ROIC engine with explicitly synthetic contract facts."""

    @classmethod
    def setUpClass(cls):
        class Captured(Exception): pass
        original = argparse.ArgumentParser.parse_args
        def capture(parser, *a, **k):
            cls.args = original(parser, *a, **k)
            raise Captured
        argv = ["model", "--codes", "000938", "--value-model", "roic",
                "--roic-nopat-source", "conditional3", "--roic-growth", "hybrid",
                "--roic-cycle-guard", "peak", "--roic-trail-weight", "0"]
        try:
            with patch("sys.argv", argv), patch.object(argparse.ArgumentParser, "parse_args", capture):
                model.main()
        except Captured:
            pass
        cls.series = model.load_financials({"000938"})["000938"]
        cls.years = model.roic_inputs.load_statements({"000938"},
                       model.ROOT / "data/interim/company_review_20260910/statements")

    def event(self):
        e = fixture(); e["security_code"] = "000938"
        e["snapshot"]["shares"] = 2860079874
        for k in ("total_equity", "parent_equity", "minority_equity", "reported_debt",
                  "cash_and_trading_assets", "annual_revenue", "annual_net_profit",
                  "annual_minority_profit", "ttm_net_profit"):
            e["snapshot"][k] *= 1e7
        for k in ("minority_equity", "redemption_liability", "dividend_liability",
                  "liability_in_reported_debt", "annual_net_profit", "annual_minority_profit"):
            e["snapshot"]["subjects"][0][k] *= 1e7
        return e

    def build(self, event, b2=False):
        args = copy.copy(self.args)
        args.ttm_trust = "on" if b2 else "off"
        with patch.object(mc, "registry", return_value={"000938": [event]}), \
                patch.dict(model.ROIC_YEARS, self.years):
            return model.build_band("000938", "fixture", "L2", self.series, [], "2026-06-30", args)

    def test_candidate_and_b2_use_snapshot_and_consolidated_ttm(self):
        for b2 in (False, True):
            b = self.build(self.event(), b2)
            self.assertEqual(b.status, "ok", b.reason)
            self.assertEqual((b.minority_share, b.minority_share_basis), (0, "event_residual_earnings"))
            self.assertEqual((b.ttm_factor, b.shares_est), (1.2, 2860079874))
            self.assertEqual((b.external_equity_ps, b.external_equity_cum_ps), (0, 0))

    def test_migration_leaves_full_model_and_sensitivity_unchanged(self):
        a = self.event(); b = copy.deepcopy(a)
        b["snapshot"]["reported_debt"] -= 250e7
        b["snapshot"]["subjects"][0]["liability_in_reported_debt"] = 0
        for b2 in (False, True):
            x, y = self.build(a, b2), self.build(b, b2)
            self.assertEqual(model.band_row(x, "L2"), model.band_row(y, "L2"))

    def test_zero_growth_uses_same_bridge(self):
        with patch.object(model.roic_inputs, "normalized_roic", return_value=.001):
            b = self.build(self.event())
        self.assertEqual(b.status, "ok", b.reason)
        self.assertEqual(b.roic_path, "zero_growth")
        ev = b.nopat_ps / b.wacc
        nd, _ = mc.equity_bridge(ev, b.fin_net_debt_ps, b.minority_book_ps,
                                b.minority_share, fixed_claim=b.minority_fixed_claim_ps)
        self.assertAlmostEqual(b.value, ev - nd)

    def test_later_same_period_reconciliation_restores_only_when_known(self):
        e = self.event(); e["known_from"] = "2026-09-10"
        prior = dict(e, event_id="prior", status="unresolved", known_from="2026-08-29")
        with patch.object(mc, "registry", return_value={"000938": [prior, e]}), \
                patch.dict(model.ROIC_YEARS, self.years):
            old = model.build_band("000938", "fixture", "L2", self.series, [], "2026-06-30", self.args)
            new = model.build_band("000938", "fixture", "L2", self.series, [], "2026-06-30",
                                   self.args, known_from="2026-09-10")
            self.assertEqual((old.minority_claim_status, new.status), ("blocked", "ok"))
            self.assertEqual(new.available_at, "2026-09-10")
            self.assertEqual(len(model.applicable_bands([old, new])), 2)
            prices = [(d, 10) for d in ("2020-01-01", "2026-09-09", "2026-09-10")]
            states = model.daily_states("000938", [old, new], prices, [])
            self.assertEqual([r["date"] for r in states], ["2026-09-10"])


if __name__ == "__main__":
    unittest.main()
