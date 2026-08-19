#!/usr/bin/env python3
"""Materialize A-share earnings preannouncements (业绩预告) from Eastmoney.

Feeds the §7.5.1 express-review queue and the pool refresh summary (§7.1).
Re-run every scan day per §9.1 step 0 — disclosures arrive daily, and a stale
file silently closes the §7.4/§7.5.1 event inlet. Raw-first: the full-market
forecast list for one report date is saved with provenance (retrieval time,
source); consumers filter by their own code lists. Field notes (validated
2026-07-17): PREDICT_FINANCE_CODE 004=归母净利, 005=扣非净利, 006=营业收入;
amounts in CNY; PREYEAR_SAME_PERIOD = 去年同期值.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_earnings_forecasts.csv"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"

FIELDNAMES = [
    "security_code",
    "security_name",
    "report_date",
    "notice_date",
    "predict_finance_code",
    "predict_finance",
    "predict_type",
    "predict_amt_lower",
    "predict_amt_upper",
    "add_amp_lower",
    "add_amp_upper",
    "preyear_same_period",
    "is_latest",
    "source",
    "retrieved_at_utc",
]


def latest_ended_quarter_end(today: date | None = None) -> str:
    """最近一个已结束的季度报告期末（§9.1 步骤 0 缺省口径）。"""
    current = today or datetime.now(timezone.utc).date()
    for month, day in ((9, 30), (6, 30), (3, 31)):
        end = date(current.year, month, day)
        if current > end:
            return end.isoformat()
    return f"{current.year - 1}-12-31"


def fetch_pages(report_date: str, timeout: float, page_size: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "sortColumns": "NOTICE_DATE,SECURITY_CODE",
                "sortTypes": "-1,1",
                "pageSize": page_size,
                "pageNumber": page,
                "reportName": "RPT_PUBLIC_OP_NEWPREDICT",
                "columns": "ALL",
                "filter": f"(REPORT_DATE='{report_date}')",
            }
        )
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
        data = ((payload.get("result") or {}).get("data")) or []
        rows.extend(data)
        pages = int((payload.get("result") or {}).get("pages") or 0)
        if page >= pages or not data:
            return rows
        page += 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-date",
        default=None,
        help="报告期，如 2026-06-30（中报）；缺省自动取最近一个已结束的季度报告期末。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args()

    report_date = args.report_date or latest_ended_quarter_end()
    raw = fetch_pages(report_date, args.timeout, args.page_size)
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_rows = [
        {
            "security_code": str(item.get("SECURITY_CODE", "")).zfill(6),
            "security_name": item.get("SECURITY_NAME_ABBR", ""),
            "report_date": str(item.get("REPORT_DATE", ""))[:10],
            "notice_date": str(item.get("NOTICE_DATE", ""))[:10],
            "predict_finance_code": item.get("PREDICT_FINANCE_CODE", ""),
            "predict_finance": item.get("PREDICT_FINANCE", ""),
            "predict_type": item.get("PREDICT_TYPE", ""),
            "predict_amt_lower": item.get("PREDICT_AMT_LOWER", ""),
            "predict_amt_upper": item.get("PREDICT_AMT_UPPER", ""),
            "add_amp_lower": item.get("ADD_AMP_LOWER", ""),
            "add_amp_upper": item.get("ADD_AMP_UPPER", ""),
            "preyear_same_period": item.get("PREYEAR_SAME_PERIOD", ""),
            "is_latest": item.get("IS_LATEST", ""),
            "source": "eastmoney:RPT_PUBLIC_OP_NEWPREDICT",
            "retrieved_at_utc": retrieved_at,
        }
        for item in raw
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"wrote {len(out_rows)} forecast rows (report_date={report_date}) to {args.output}")


if __name__ == "__main__":
    main()
