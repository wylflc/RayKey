#!/usr/bin/env python3
"""Regression tests for valuation-card quote dating."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

import apply_valuation_band_cards as app


class QuoteDateTest(unittest.TestCase):
    def test_uses_provider_trade_date(self) -> None:
        self.assertEqual(app.quote_date("20260825161500", "2026-08-26"), "2026-08-25")

    def test_falls_back_when_provider_time_is_missing(self) -> None:
        self.assertEqual(app.quote_date("", "2026-08-26"), "2026-08-26")

    def test_falls_back_when_provider_time_is_malformed(self) -> None:
        self.assertEqual(app.quote_date("2026-08-25", "2026-08-26"), "2026-08-26")




class ModelEvaluatedTest(unittest.TestCase):
    """`_load_model_evaluated` 必须连报告期一起返回，无法估值行的两列才对得上同一期。"""

    FIELDS = ("security_code", "report_date", "available_at", "status",
              "model_evaluated_at", "model_evaluated_report_date")

    def _file(self, rows) -> Path:
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                         newline="", encoding="utf-8")
        w = csv.DictWriter(fh, fieldnames=self.FIELDS)
        w.writeheader()
        w.writerows(rows)
        fh.close()
        return Path(fh.name)

    def test_rejected_row_still_reports_its_period(self) -> None:
        """广东宏大型：唯一的行是 2026 中报被判拒，评估期就是它自己。"""
        path = self._file([{"security_code": "002683", "report_date": "2026-06-30",
                            "available_at": "2026-08-25", "status": "rejected",
                            "model_evaluated_at": "2026-08-25",
                            "model_evaluated_report_date": "2026-06-30"}])
        got = app._load_model_evaluated(path)
        self.assertEqual(got["002683"], {"at": "2026-08-25", "report_date": "2026-06-30"})

    def test_takes_latest_evaluated_not_the_adopted_band(self) -> None:
        """中芯国际型：采纳带停在 2023Q3（单行），评估期由产出方另写一列给出。"""
        path = self._file([
            {"security_code": "688981", "report_date": "2023-09-30", "available_at": "2023-10-31",
             "status": "ok", "model_evaluated_at": "2026-08-28",
             "model_evaluated_report_date": "2026-06-30"},
        ])
        got = app._load_model_evaluated(path)
        self.assertEqual(got["688981"]["at"], "2026-08-28")
        self.assertEqual(got["688981"]["report_date"], "2026-06-30")

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(app._load_model_evaluated(Path("/nonexistent/x.csv")), {})


class ReportEventTest(unittest.TestCase):
    def test_period_maps_to_event_name(self) -> None:
        for period, name in (("2026-06-30", "中报"), ("2026-03-31", "一季报"),
                             ("2026-09-30", "三季报"), ("2025-12-31", "年报")):
            self.assertEqual(app.REPORT_EVENT.get(period[5:10], "定期报告"), name)

    def test_falls_back_to_row_period_when_column_missing(self) -> None:
        """旧文件没有 `model_evaluated_report_date` 列时退回本行报告期，不报错。"""
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                         newline="", encoding="utf-8")
        w = csv.DictWriter(fh, fieldnames=("security_code", "report_date",
                                           "available_at", "model_evaluated_at"))
        w.writeheader()
        w.writerow({"security_code": "600519", "report_date": "2026-06-30",
                    "available_at": "2026-08-15", "model_evaluated_at": "2026-08-15"})
        fh.close()
        got = app._load_model_evaluated(Path(fh.name))
        self.assertEqual(got["600519"], {"at": "2026-08-15", "report_date": "2026-06-30"})


if __name__ == "__main__":
    unittest.main()
