#!/usr/bin/env python3
"""Materialize A-share periodic-report & express-report disclosures from Eastmoney.

Companion to fetch_a_share_earnings_forecasts.py, closing the other half of the
§9.1 step-0 disclosure sync (v1.18): 正式定期报告（RPT_LICO_FN_CPD，公告日 = 实际
披露日）与业绩快报（RPT_FCI_PERFORMANCEE）。Without this file the update queue
only sees forecasts — an actual 中报/快报 landing after the last valuation
review stays invisible (判例: 苏泊尔 2026-07-22 盘后 H1 快报, forecast-only
sync 无法看见). Re-run every scan day per §9.1 step 0. Raw-first: full-market
rows for one report date with provenance; consumers filter by their own code
lists. Field notes (validated 2026-07-22): RPT_LICO_FN_CPD keys report period
as REPORTDATE (no underscore), 净利同比 = SJLTZ; RPT_FCI_PERFORMANCEE keys it
as REPORT_DATE, 净利同比 = JLRTBZCL; both give NOTICE_DATE and YSTZ (营收同比);
amounts in CNY.
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
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_report_disclosures.csv"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"

DATASETS = {
    # disclosure_type -> (reportName, report-date column, 净利同比 field)
    "periodic_report": ("RPT_LICO_FN_CPD", "REPORTDATE", "SJLTZ"),
    "express_report": ("RPT_FCI_PERFORMANCEE", "REPORT_DATE", "JLRTBZCL"),
}

FIELDNAMES = [
    "security_code",
    "security_name",
    "report_date",
    "notice_date",
    "disclosure_type",
    "report_label",
    "parent_netprofit",
    "total_operate_income",
    "netprofit_yoy",
    "revenue_yoy",
    "is_new",
    "source",
    "retrieved_at_utc",
]


def latest_ended_quarter_end(today: date | None = None) -> str:
    """最近一个已结束的季度报告期末（§9.1 步骤 0 缺省口径，与预告脚本一致）。"""
    current = today or datetime.now(timezone.utc).date()
    for month, day in ((9, 30), (6, 30), (3, 31)):
        end = date(current.year, month, day)
        if current > end:
            return end.isoformat()
    return f"{current.year - 1}-12-31"


def fetch_pages(report_name: str, date_column: str, report_date: str, timeout: float, page_size: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "sortColumns": "NOTICE_DATE,SECURITY_CODE",
                "sortTypes": "-1,1",
                "pageSize": page_size,
                "pageNumber": page,
                "reportName": report_name,
                "columns": "ALL",
                "filter": f"({date_column}='{report_date}')",
            }
        )
        request = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "Mozilla/5.0"})
        payload = None
        for attempt in (1, 2):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    payload = json.loads(response.read().decode("utf-8", "ignore"))
                break
            except (TimeoutError, OSError):
                if attempt == 2:
                    raise
        data = ((payload.get("result") or {}).get("data")) or []
        rows.extend(data)
        pages = int((payload.get("result") or {}).get("pages") or 0)
        if page >= pages or not data:
            return rows
        page += 1


def normalize(item: dict[str, object], disclosure_type: str, netprofit_yoy_field: str, retrieved_at: str) -> dict[str, object]:
    report_name = DATASETS[disclosure_type][0]
    label = item.get("DATATYPE") or ("业绩快报" if disclosure_type == "express_report" else "")
    return {
        "security_code": str(item.get("SECURITY_CODE", "")).zfill(6),
        "security_name": item.get("SECURITY_NAME_ABBR", ""),
        "report_date": str(item.get("REPORTDATE") or item.get("REPORT_DATE") or "")[:10],
        "notice_date": str(item.get("NOTICE_DATE", ""))[:10],
        "disclosure_type": disclosure_type,
        "report_label": label,
        "parent_netprofit": item.get("PARENT_NETPROFIT", ""),
        "total_operate_income": item.get("TOTAL_OPERATE_INCOME", ""),
        "netprofit_yoy": item.get(netprofit_yoy_field, ""),
        "revenue_yoy": item.get("YSTZ", ""),
        "is_new": item.get("ISNEW", ""),
        "source": f"eastmoney:{report_name}",
        "retrieved_at_utc": retrieved_at,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-date",
        default=None,
        help="报告期，如 2026-06-30（中报）；缺省自动取最近一个已结束的季度报告期末。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--page-size", type=int, default=500)
    args = parser.parse_args()

    report_date = args.report_date or latest_ended_quarter_end()
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_rows: list[dict[str, object]] = []
    counts: dict[str, int] = {}
    for disclosure_type, (report_name, date_column, yoy_field) in DATASETS.items():
        raw = fetch_pages(report_name, date_column, report_date, args.timeout, args.page_size)
        counts[disclosure_type] = len(raw)
        out_rows.extend(normalize(item, disclosure_type, yoy_field, retrieved_at) for item in raw)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(out_rows)
    print(
        f"wrote {len(out_rows)} disclosure rows (report_date={report_date}; "
        f"periodic {counts.get('periodic_report', 0)}, express {counts.get('express_report', 0)}) to {args.output}"
    )


if __name__ == "__main__":
    main()
