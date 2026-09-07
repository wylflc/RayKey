"""已公告的次日分红不能提前折进信号日的现价估值。"""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apply_forecast_band_overlay as overlay


class CorporateActionDateTest(unittest.TestCase):
    def test_future_ex_date_waits_until_effective_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bands, actions = root / "bands.csv", root / "actions.csv"
            base = dict(security_code="300760", security_name="迈瑞医疗",
                        report_date="2026-06-30", notice_date="2026-08-28",
                        available_at="2026-08-28", status="ok",
                        intrinsic_value="92.4423", band_low="83.1981", band_high="101.6866")
            with actions.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["security_code", "ex_dividend_date", "cash_per_share", "share_ratio"])
                w.writerow(["300760", "2026-09-08", "1.33", "0"])
            for day, expected in [("2026-09-07", 92.4423), ("2026-09-08", 91.1123)]:
                with self.subTest(day=day):
                    with bands.open("w", newline="") as f:
                        w = csv.DictWriter(f, fieldnames=list(base))
                        w.writeheader()
                        w.writerow(base)
                    argv = ["apply_forecast_band_overlay.py", "--signal-date", day,
                            "--bands", str(bands), "--corporate-actions", str(actions)]
                    for option in ["forecasts", "disclosures", "overrides", "pool"]:
                        argv.extend([f"--{option}", str(root / "missing.csv")])
                    with patch("sys.argv", argv), patch.object(overlay, "load_financials", return_value={}), \
                            contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(overlay.main(), 0)
                    with bands.open(encoding="utf-8-sig") as f:
                        result = next(csv.DictReader(f))
                    self.assertAlmostEqual(float(result["intrinsic_value"]), expected, places=4)
                    self.assertEqual(bool(result["exright_note"]), day == "2026-09-08")


if __name__ == "__main__":
    unittest.main()
