#!/usr/bin/env python3
"""Fetch authoritative source links for A-share deep-review batches.

This script only collects evidence links. It does not assign ratings or make
watchlist decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data/interim/a_share_authoritative_deep_review_queue.csv"
OUTPUT_DIR = ROOT / "data/interim"
CNINFO_BASE = "https://www.cninfo.com.cn"
SOURCE_FETCHED_AT_UTC = "2026-06-14T00:00:00+00:00"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def post_json(url: str, data: dict[str, str], referer: str) -> object:
    encoded = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
            "Origin": "https://www.cninfo.com.cn",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch JSON from {url}: {last_error}")


def get_cninfo_org_id(code: str) -> str:
    try:
        rows = post_json(
            f"{CNINFO_BASE}/new/information/topSearch/query",
            {"keyWord": code, "maxNum": "10"},
            f"{CNINFO_BASE}/new/index",
        )
    except RuntimeError:
        return ""
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if str(row.get("code", "")) == code:
            return str(row.get("orgId", ""))
    return ""


def announcement_query(code: str, exchange: str, org_id: str, category: str) -> list[dict[str, object]]:
    column = "sse" if exchange == "SSE" else "szse"
    data = {
        "pageNum": "1",
        "pageSize": "10",
        "column": column,
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{org_id}" if org_id else code,
        "searchkey": "",
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": "2025-01-01~2026-06-14",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    response = post_json(
        f"{CNINFO_BASE}/new/hisAnnouncement/query",
        data,
        f"{CNINFO_BASE}/new/disclosure/stock?stockCode={code}",
    )
    if not isinstance(response, dict):
        return []
    return list(response.get("announcements") or [])


def pick_announcement(code: str, exchange: str, org_id: str, categories: list[str]) -> dict[str, str]:
    candidates: list[dict[str, object]] = []
    for category in categories:
        try:
            candidates.extend(announcement_query(code, exchange, org_id, category))
        except RuntimeError:
            pass
        time.sleep(0.15)
    def title_period_rank(item: dict[str, object]) -> tuple[int, int, int]:
        title = str(item.get("announcementTitle") or "")
        year_match = re.search(r"(20\d{2})年", title)
        year = int(year_match.group(1)) if year_match else 0
        if "第三季度" in title or "三季度" in title:
            period = 3
        elif "半年度" in title:
            period = 2
        elif "第一季度" in title or "一季度" in title:
            period = 1
        elif "年度" in title:
            period = 4
        else:
            period = 0
        return (year, period, int(item.get("announcementTime") or 0))

    candidates = sorted(candidates, key=title_period_rank, reverse=True)
    for item in candidates:
        title = str(item.get("announcementTitle") or "")
        adjunct_url = str(item.get("adjunctUrl") or "")
        if not adjunct_url or "摘要" in title or "英文" in title:
            continue
        return {
            "title": title,
            "url": f"{CNINFO_BASE}/new/announcement/download?bulletinId={item.get('announcementId')}&announceTime={item.get('announcementTime')}"
            if item.get("announcementId")
            else f"{CNINFO_BASE}/{adjunct_url}",
            "fallback_pdf_url": f"{CNINFO_BASE}/{adjunct_url}",
            "date_ms": str(item.get("announcementTime") or ""),
        }
    return {"title": "", "url": "", "fallback_pdf_url": "", "date_ms": ""}


def fetch_research_report(code: str) -> dict[str, str]:
    params = {
        "pageNo": "1",
        "pageSize": "10",
        "code": code,
        "industryCode": "*",
        "industry": "*",
        "rating": "*",
        "ratingChange": "*",
        "beginTime": "2025-01-01",
        "endTime": "2026-06-14",
        "fields": "",
        "qType": "0",
        "orgCode": "",
        "rcode": "",
        "p": "1",
        "pageNum": "1",
        "pageNumber": "1",
        "_": "1780000000000",
    }
    url = "https://reportapi.eastmoney.com/report/list?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://data.eastmoney.com/report/stock.jshtml",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    reports = payload.get("data") or []
    for report in reports:
        info_code = str(report.get("infoCode") or "")
        if not info_code:
            continue
        return {
            "title": str(report.get("title") or ""),
            "org": str(report.get("orgName") or report.get("orgSName") or ""),
            "researcher": str(report.get("researcher") or ""),
            "publish_date": str(report.get("publishDate") or ""),
            "url": f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf",
            "info_code": info_code,
        }
    return {"title": "", "org": "", "researcher": "", "publish_date": "", "url": "", "info_code": ""}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()

    rows = [row for row in read_csv(QUEUE) if row["review_batch_id"] == args.batch_id]
    output = OUTPUT_DIR / f"a_share_authoritative_sources_{args.batch_id}.csv"
    fields = [
        "review_batch_id",
        "security_code",
        "security_name",
        "listed_company_name",
        "exchange",
        "cninfo_org_id",
        "annual_report_title",
        "annual_report_source_url",
        "annual_report_fallback_pdf_url",
        "current_report_title",
        "current_report_source_url",
        "current_report_fallback_pdf_url",
        "official_disclosure_page",
        "research_report_title",
        "research_report_org",
        "research_reporter",
        "research_report_publish_date",
        "research_report_source_url",
        "research_report_info_code",
        "source_fetched_at_utc",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            code = row["security_code"]
            org_id = get_cninfo_org_id(code)
            time.sleep(0.15)
            annual = pick_announcement(code, row["exchange"], org_id, ["category_ndbg_szsh"])
            current = pick_announcement(
                code,
                row["exchange"],
                org_id,
                ["category_yjdbg_szsh", "category_sjdbg_szsh", "category_bndbg_szsh"],
            )
            try:
                research = fetch_research_report(code)
            except Exception:
                research = {"title": "", "org": "", "researcher": "", "publish_date": "", "url": "", "info_code": ""}
            writer.writerow(
                {
                    "review_batch_id": row["review_batch_id"],
                    "security_code": code,
                    "security_name": row["security_name"],
                    "listed_company_name": row["listed_company_name"],
                    "exchange": row["exchange"],
                    "cninfo_org_id": org_id,
                    "annual_report_title": annual["title"],
                    "annual_report_source_url": annual["url"],
                    "annual_report_fallback_pdf_url": annual["fallback_pdf_url"],
                    "current_report_title": current["title"],
                    "current_report_source_url": current["url"],
                    "current_report_fallback_pdf_url": current["fallback_pdf_url"],
                    "official_disclosure_page": f"{CNINFO_BASE}/new/disclosure/stock?stockCode={code}",
                    "research_report_title": research["title"],
                    "research_report_org": research["org"],
                    "research_reporter": research["researcher"],
                    "research_report_publish_date": research["publish_date"],
                    "research_report_source_url": research["url"],
                    "research_report_info_code": research["info_code"],
                    "source_fetched_at_utc": SOURCE_FETCHED_AT_UTC,
                }
            )
            time.sleep(0.25)

    print(output.relative_to(ROOT))
    print("rows", len(rows))


if __name__ == "__main__":
    main()
