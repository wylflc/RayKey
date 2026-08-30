#!/usr/bin/env python3
"""SSE universe row filtering regression tests (terminated listings must not enter the universe)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_a_share_universe import is_terminated_sse_row


class TerminatedSseRowTest(unittest.TestCase):
    def test_live_row_kept(self) -> None:
        row = {"A_STOCK_CODE": "600000", "SEC_NAME_CN": "浦发银行", "DELIST_DATE": "-", "STATE_CODE": "2"}
        self.assertFalse(is_terminated_sse_row(row))

    def test_delist_date_marks_terminated(self) -> None:
        row = {"A_STOCK_CODE": "600001", "SEC_NAME_CN": "-", "COMPANY_ABBR": "邯郸钢铁", "DELIST_DATE": "20091229", "STATE_CODE": "3"}
        self.assertTrue(is_terminated_sse_row(row))

    def test_state_code_alone_marks_terminated(self) -> None:
        self.assertTrue(is_terminated_sse_row({"SEC_NAME_CN": "退市观典", "DELIST_DATE": "-", "STATE_CODE": "3"}))

    def test_dash_name_alone_marks_terminated(self) -> None:
        self.assertTrue(is_terminated_sse_row({"SEC_NAME_CN": "-", "DELIST_DATE": "-", "STATE_CODE": "2"}))

    def test_st_row_is_not_terminated(self) -> None:
        self.assertFalse(is_terminated_sse_row({"SEC_NAME_CN": "*ST蓝光", "DELIST_DATE": "-", "STATE_CODE": "7"}))


if __name__ == "__main__":
    unittest.main()
