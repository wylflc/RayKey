#!/usr/bin/env python3
"""OI-162：扫描、跟踪、阅读版、成交估值在利率/除权/缺带时同源。"""
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import build_a_share_core_valuation_pool as pool
import screen_daily_volume_price_signals as scan
import track_holdings_daily as tracker
from resolve_trade_valuation import trade_valuation


class LiveFinancialValuationTests(unittest.TestCase):
    def check_consumers(self, code, name, value, bands):
        day = "2026-09-07"
        holding = {"security_code": code, "security_name": name, "current_shares": "100",
                   "cost_basis": "40", "entry_stop_price": "30"}
        stale = {**holding, "market_type": "A_SHARE", "fair_price_low": "90",
                 "fair_price_high": "110", "pool_as_of": day}
        with tempfile.TemporaryDirectory() as tmp:
            hp = Path(tmp) / "holdings.csv"
            with hp.open("w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(holding)); w.writeheader(); w.writerow(holding)
            with (patch.object(scan, "bank_dividend_intrinsic", return_value=value),
                  patch.object(scan, "_default_rf", return_value=0.02),
                  patch.object(tracker, "MODEL_BANDS", bands), patch.object(tracker, "CAND_BANDS", bands),
                  patch.object(tracker, "load_pool", return_value={code: stale}),
                  patch.object(tracker, "resolve_prices", return_value=({code: 40}, {}, {}, "收盘")),
                  patch.object(pool, "MODEL_BANDS", bands), patch.object(pool, "VALUATION_AS_OF", day)):
                row = {**holding, "close": 40}
                scan.attach_model_pv([row], bands, day, None)
                tracked = tracker.track(hp, hp, date.fromisoformat(day), "", 1)[0]
                displayed = pool.display_cells(stale, {"price": 40})
                trade = trade_valuation(code, name, day, 40, bands, bands)
        if value:
            self.assertEqual(row["model_pv"], round(40 / value, 4))
            self.assertEqual(tracked["pv"], f"{40/value:.2f}")
            self.assertAlmostEqual(float(tracked["fair_price_low"]), value * 0.9, places=3)
            self.assertEqual(displayed["fair_value"], f"{value:.2f}")
            self.assertEqual(displayed["pv"], f"{40/value:.3f}")
            self.assertAlmostEqual(trade["candidate"]["pv"], 40/value)
            self.assertEqual(trade["candidate"], trade["hold"])
        else:
            self.assertEqual(row["model_pv"], "")
            self.assertEqual(tracked["pv"], "")
            self.assertEqual(tracked["action"], "数据缺失")
            self.assertEqual(displayed["fair_value"], "—")
            self.assertIsNone(trade["candidate"]["pv"])

    def test_bank_and_insurance_ignore_stale_band(self):
        for code, name in (("600036", "招商银行"), ("601318", "中国平安")):
            with self.subTest(code=code):
                self.check_consumers(code, name, 53.7737, {code: {"intrinsic_value": "100"}})

    def test_financial_valuation_without_static_band(self):
        self.check_consumers("600036", "招商银行", 50, {})

    def test_missing_dividend_does_not_fall_back_to_stale_band(self):
        self.check_consumers("601318", "中国平安", None, {"601318": {"intrinsic_value": "100"}})

    def test_rf_uses_signal_date_and_latest_observation_not_file_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "data/reference").mkdir(parents=True)
            (root / "data/reference/cost_of_equity_inputs.csv").write_text(
                "observed_on,risk_free_rate\n2026-09-08,0.01\n2026-09-04,0.02\n2026-08-31,0.03\n")
            with patch.object(scan, "ROOT", root):
                self.assertEqual(scan._default_rf("2026-09-07"), 0.02)
                self.assertEqual(scan._default_rf("2026-09-01"), 0.03)
                self.assertIsNone(scan._default_rf("2026-08-01"))

    def test_exright_day_is_applied_once_by_shared_resolver(self):
        from divspread_dividend import Distribution
        code = "600036"
        distributions = {code: [Distribution("2026-04-01", "2025-12-31", 2.0, "2026-09-07")]}
        with (patch.object(scan, "_dividend_distributions", return_value=distributions),
              patch.object(scan, "_corporate_actions", return_value={code: [{"ex_dividend_date": "2026-09-07", "cash_per_share": "1.0"}]})):
            before, _ = scan.resolve_live_band(code, "招商银行", "2026-09-06", {}, 0.02)
            after, _ = scan.resolve_live_band(code, "招商银行", "2026-09-07", {}, 0.02)
        self.assertAlmostEqual(before["intrinsic_value"] - after["intrinsic_value"], 1.0)


if __name__ == "__main__":
    unittest.main()
