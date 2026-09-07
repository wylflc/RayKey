"""名单恢复不得回填到年报日或改写此前成员历史。"""
import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_moat_panel as panel


class MoatPanelDatesTest(unittest.TestCase):
    def test_year_convention_and_invalid_calendar_date(self):
        self.assertEqual(panel.entry_date("2022"), "2023-04-30")
        with self.assertRaises(ValueError):
            panel.entry_date("2026-02-30")

    def test_restoration_and_new_member_only_take_effect_on_resolution_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fields = ["effective_from", "effective_to", "screen_year",
                      "security_code", "security_name", "avg_roe_3y", "rank"]
            v5, verdicts, pool = root / "base.csv", root / "verdicts.csv", root / "pool.csv"
            with v5.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(fields)
                w.writerow(["2023-04-30", "", "2023", "002409", "雅克科技", "", ""])
                w.writerow(["2018-04-30", "", "2018", "600036", "招商银行", "", ""])
            with verdicts.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["security_code", "security_name", "worth_from", "worth_to", "rule", "reason"])
                w.writerow(["002409", "雅克科技", "2022", "2026-09-06", "historical", "prior interval"])
                w.writerow(["002409", "雅克科技", "2026-09-07", "9999", "resolution", "restore"])
                w.writerow(["920599", "同力股份", "2026-09-07", "9999", "resolution", "new interval"])
            with pool.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["security_code", "security_name", "market_type"])
                for code, name in [("002409", "雅克科技"), ("920599", "同力股份"), ("600036", "招商银行")]:
                    w.writerow([code, name, "A_SHARE"])
            with patch.multiple(panel, PIT=root, V5=v5, VERDICTS=verdicts, POOL=pool), \
                    patch("sys.argv", ["build_moat_panel.py", "--today", "2026-09-07"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(panel.main(), 0)
            with (root / "panel_moat_bank_v6b.csv").open() as f:
                rows = list(csv.DictReader(f))
            def active(day):
                return [r["security_code"] for r in rows
                        if r["effective_from"] <= day <= (r["effective_to"] or "9999-12-31")]
            self.assertEqual(set(active("2026-05-01")), {"002409", "600036"})
            self.assertEqual(set(active("2026-09-06")), {"002409", "600036"})
            self.assertEqual(set(active("2026-09-07")), {"002409", "600036", "920599"})
            self.assertEqual(len(active("2026-09-07")), 3)
            restored = [r for r in rows if r["security_code"] == "002409"]
            self.assertEqual([r["effective_from"] for r in restored], ["2023-04-30", "2026-09-07"])
            self.assertEqual([r["screen_year"] for r in restored], ["2023", "2026"])


if __name__ == "__main__":
    unittest.main()
