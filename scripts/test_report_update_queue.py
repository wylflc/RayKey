#!/usr/bin/env python3
"""§7.1 更新队列的时点隔离与信号日→证据日映射。"""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_report_update_queue as q


def _tier(code: str) -> dict[str, str]:
    return {"security_code": code, "security_name": f"N{code}", "quality_tier": "L2",
            "reviewed_at_utc": "2026-08-01T00:00:00Z", "evidence_available_at": ""}


def _pool(code: str, reviewed: str) -> dict[str, str]:
    return {"security_code": code, "valuation_reviewed_at": reviewed, "evidence_available_at": reviewed}


class ReportUpdateQueueAsOfTest(unittest.TestCase):
    def test_signal_date_automatically_exposes_next_workday_notice(self) -> None:
        disclosures = [
            {"security_code": "000651", "disclosure_type": "periodic_report",
             "notice_date": "2026-08-27", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue_for_signal(
            [], [_tier("000651")], [_pool("000651", "2026-04-29")], [], [], disclosures, "2026-08-26"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["as_of"], "2026-08-27")
        self.assertEqual(rows[0]["latest_periodic_notice_date"], "2026-08-27")

    def test_future_dated_notice_is_invisible(self) -> None:
        disclosures = [
            {"security_code": "000001", "disclosure_type": "periodic_report",
             "notice_date": "2026-08-25", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue([], [_tier("000001")], [_pool("000001", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(rows, [])
        rows = q.build_queue([], [_tier("000001")], [_pool("000001", "2026-08-20")], [], [], disclosures, "2026-08-25")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_periodic_notice_date"], "2026-08-25")
        self.assertEqual(rows[0]["buy_blocked"], "review_pending")

    def test_earlier_visible_row_still_used_when_latest_is_future(self) -> None:
        disclosures = [
            {"security_code": "000002", "disclosure_type": "express_report",
             "notice_date": "2026-08-25", "report_date": "2026-06-30", "report_label": "快报"},
            {"security_code": "000002", "disclosure_type": "express_report",
             "notice_date": "2026-08-22", "report_date": "2026-06-30", "report_label": "快报"},
        ]
        rows = q.build_queue([], [_tier("000002")], [_pool("000002", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["latest_express_notice_date"], "2026-08-22")

    def test_forecast_respects_as_of(self) -> None:
        forecasts = [
            {"security_code": "000003", "is_latest": "T", "notice_date": "2026-08-25", "predict_type": "预增"},
        ]
        rows = q.build_queue([], [_tier("000003")], [_pool("000003", "2026-08-20")], [], forecasts, [], "2026-08-24")
        self.assertEqual(rows, [])
        rows = q.build_queue([], [_tier("000003")], [_pool("000003", "2026-08-20")], [], forecasts, [], "2026-08-25")
        self.assertEqual(len(rows), 1)
        self.assertIn("forecast_after_last_valuation_review", str(rows[0]["queue_reasons"]))

    def test_blank_notice_date_is_invisible(self) -> None:
        disclosures = [
            {"security_code": "000004", "disclosure_type": "periodic_report",
             "notice_date": "", "report_date": "2026-06-30", "report_label": "2026 中报"},
        ]
        rows = q.build_queue([], [_tier("000004")], [_pool("000004", "2026-08-20")], [], [], disclosures, "2026-08-24")
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
