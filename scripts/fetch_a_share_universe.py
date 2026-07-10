#!/usr/bin/env python3
"""Fetch the current mainland China A-share security universe to CSV.

The script uses public exchange endpoints for Shanghai, Shenzhen, and Beijing
A-share securities. It keeps provider and retrieval metadata in every row so
later screening runs can audit which universe snapshot they used.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = Path("data/raw/a_share_securities.csv")

SSE_ENDPOINT = "https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER = "https://www.sse.com.cn/assortment/stock/list/"
SSE_STOCK_TYPES = {
    "1": "main_board",
    "8": "star_market",
}

SZSE_ENDPOINT = "http://www.szse.cn/api/report/ShowReport/data"
SZSE_REFERER = "http://www.szse.cn/market/product/stock/list/index.html"
SZSE_BOARD_MAP = {
    "主板": "main_board",
    "创业板": "chinext",
}

BSE_ENDPOINT = "https://www.bse.cn/nqxxController/nqxxCnzq.do"
BSE_REFERER = "https://www.bse.cn/nq/listedcompany.html"

CSV_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "board",
    "listed_company_name",
    "security_name",
    "currency",
    "listing_date",
    "industry",
    "region",
    "source_provider",
    "source_dataset",
    "source_retrieved_at_utc",
    "raw_identifier",
    "source_url",
]

EXCHANGE_SORT_ORDER = {"SSE": 0, "SZSE": 1, "BSE": 2}


class FetchError(RuntimeError):
    """Raised when a provider response is unavailable or structurally invalid."""


def request_json(url: str, referer: str, timeout: int) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/javascript,*/*;q=0.01",
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise FetchError(f"Failed to fetch JSON from {url}: {exc}") from exc


def request_text_post(url: str, referer: str, form_data: list[tuple[str, str]], timeout: int) -> str:
    encoded = urllib.parse.urlencode(form_data).encode()
    request = urllib.request.Request(
        url,
        data=encoded,
        method="POST",
        headers={
            "Accept": "application/json,text/javascript,*/*;q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.bse.cn",
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        raise FetchError(f"Failed to fetch text from {url}: {exc}") from exc


def build_sse_url(stock_type: str, page_size: int) -> str:
    params = {
        "STOCK_TYPE": stock_type,
        "REG_PROVINCE": "",
        "CSRC_CODE": "",
        "STOCK_CODE": "",
        "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
        "type": "inParams",
        "isPagination": "true",
        "pageHelp.cacheSize": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.pageSize": str(page_size),
        "pageHelp.pageNo": "1",
        "pageHelp.endPage": "1",
    }
    return f"{SSE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def fetch_sse_rows(page_size: int, timeout: int) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for stock_type, board in SSE_STOCK_TYPES.items():
        url = build_sse_url(stock_type=stock_type, page_size=page_size)
        payload = request_json(url=url, referer=SSE_REFERER, timeout=timeout)
        page_help = payload.get("pageHelp") if isinstance(payload, dict) else None
        if not isinstance(page_help, dict):
            raise FetchError("SSE response missing pageHelp object")
        rows = page_help.get("data")
        total = page_help.get("total")
        if not isinstance(rows, list) or not isinstance(total, int):
            raise FetchError("SSE response missing pageHelp.data or pageHelp.total")
        if len(rows) != total:
            raise FetchError(f"SSE stockType={stock_type} fetched {len(rows)} rows, expected {total}")

        for raw in rows:
            code = clean_text(raw.get("A_STOCK_CODE"))
            security_name = clean_text(raw.get("SEC_NAME_CN") or raw.get("COMPANY_ABBR"))
            listed_company_name = clean_text(raw.get("FULL_NAME") or raw.get("COMPANY_ABBR"))
            if not code or not security_name:
                continue
            normalized.append(
                {
                    "security_code": code,
                    "symbol": f"{code}.SH",
                    "exchange": "SSE",
                    "board": board,
                    "listed_company_name": listed_company_name,
                    "security_name": security_name,
                    "currency": "CNY",
                    "listing_date": format_yyyymmdd(clean_text(raw.get("LIST_DATE"))),
                    "industry": clean_text(raw.get("CSRC_CODE_DESC")),
                    "region": clean_text(raw.get("AREA_NAME_DESC")),
                    "source_provider": "Shanghai Stock Exchange",
                    "source_dataset": f"sse_common_stock_list_stock_type_{stock_type}",
                    "source_retrieved_at_utc": "",
                    "raw_identifier": clean_text(raw.get("COMPANY_CODE")),
                    "source_url": url,
                }
            )
    return normalized


def build_szse_url(page_no: int) -> str:
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": "1110",
        "TABKEY": "tab1",
        "PAGENO": str(page_no),
        "random": "0.1",
    }
    return f"{SZSE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def fetch_szse_rows(timeout: int, pause_seconds: float) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    page_no = 1
    page_count: int | None = None
    record_count: int | None = None

    while page_count is None or page_no <= page_count:
        url = build_szse_url(page_no)
        payload = request_json(url=url, referer=SZSE_REFERER, timeout=timeout)
        if not isinstance(payload, list) or not payload:
            raise FetchError("SZSE response missing report list")
        report = payload[0]
        metadata = report.get("metadata") if isinstance(report, dict) else None
        rows = report.get("data") if isinstance(report, dict) else None
        if not isinstance(metadata, dict) or not isinstance(rows, list):
            raise FetchError("SZSE response missing metadata or data list")

        if page_count is None:
            page_count = int(metadata["pagecount"])
            record_count = int(metadata["recordcount"])

        for raw in rows:
            code = clean_text(raw.get("agdm"))
            security_name = strip_html(raw.get("agjc"))
            if not code or not security_name:
                continue
            raw_board = clean_text(raw.get("bk"))
            normalized.append(
                {
                    "security_code": code,
                    "symbol": f"{code}.SZ",
                    "exchange": "SZSE",
                    "board": SZSE_BOARD_MAP.get(raw_board, raw_board or "unknown"),
                    "listed_company_name": security_name,
                    "security_name": security_name,
                    "currency": "CNY",
                    "listing_date": clean_text(raw.get("agssrq")),
                    "industry": clean_text(raw.get("sshymc")),
                    "region": "",
                    "source_provider": "Shenzhen Stock Exchange",
                    "source_dataset": "szse_a_share_list",
                    "source_retrieved_at_utc": "",
                    "raw_identifier": code,
                    "source_url": build_szse_url(1),
                }
            )

        page_no += 1
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    if record_count is None:
        raise FetchError("SZSE response did not report record count")
    if len(normalized) != record_count:
        raise FetchError(f"SZSE fetched {len(normalized)} rows, expected {record_count}")
    return normalized


def parse_bse_jsonp(text: str) -> list[dict[str, Any]]:
    match = re.fullmatch(r"\s*null\((.*)\)\s*", text, flags=re.DOTALL)
    if not match:
        raise FetchError("BSE response did not match expected null(...) JSONP wrapper")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise FetchError(f"Failed to parse BSE JSONP payload: {exc}") from exc
    if not isinstance(payload, list):
        raise FetchError("BSE JSONP payload is not a list")
    return payload


def fetch_bse_rows(timeout: int, pause_seconds: float) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    page_no = 0
    total_pages: int | None = None
    total_elements: int | None = None

    while total_pages is None or page_no < total_pages:
        text = request_text_post(
            url=BSE_ENDPOINT,
            referer=BSE_REFERER,
            form_data=[
                ("page", str(page_no)),
                ("typejb", "T"),
                ("xxfcbj[]", "2"),
                ("xxzqdm", ""),
                ("sortfield", "xxzqdm"),
                ("sorttype", "asc"),
            ],
            timeout=timeout,
        )
        payload = parse_bse_jsonp(text)
        if not payload or not isinstance(payload[0], dict):
            raise FetchError("BSE response missing page object")

        page = payload[0]
        rows = page.get("content")
        if not isinstance(rows, list):
            raise FetchError("BSE response missing content list")
        if total_pages is None:
            total_pages = int(page["totalPages"])
            total_elements = int(page["totalElements"])

        for raw in rows:
            code = clean_text(raw.get("xxzqdm"))
            security_name = clean_text(raw.get("xxzqjc"))
            if not code or not security_name:
                continue
            normalized.append(
                {
                    "security_code": code,
                    "symbol": f"{code}.BJ",
                    "exchange": "BSE",
                    "board": "beijing_stock_exchange",
                    "listed_company_name": security_name,
                    "security_name": security_name,
                    "currency": "CNY",
                    "listing_date": format_yyyymmdd(clean_text(raw.get("xxgprq"))),
                    "industry": clean_text(raw.get("xxhyzl")),
                    "region": clean_text(raw.get("xxssdq")),
                    "source_provider": "Beijing Stock Exchange",
                    "source_dataset": "bse_listed_company_stock_list",
                    "source_retrieved_at_utc": "",
                    "raw_identifier": clean_text(raw.get("xxisin") or raw.get("xxzqdm")),
                    "source_url": BSE_ENDPOINT,
                }
            )

        page_no += 1
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    if total_elements is None:
        raise FetchError("BSE response did not report total elements")
    if len(normalized) != total_elements:
        raise FetchError(f"BSE fetched {len(normalized)} rows, expected {total_elements}")
    return normalized


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def strip_html(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def format_yyyymmdd(value: str) -> str:
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def validate_rows(rows: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        code = row["security_code"]
        if len(code) != 6 or not code.isdigit():
            raise FetchError(f"Unexpected security code: {code!r}")
        if code in seen:
            duplicates.append(code)
        seen.add(code)
    if duplicates:
        sample = ", ".join(duplicates[:10])
        raise FetchError(f"Duplicate security_code values detected: {sample}")


def finalize_rows(rows: list[dict[str, str]], retrieved_at_utc: str) -> list[dict[str, str]]:
    for row in rows:
        row["source_retrieved_at_utc"] = retrieved_at_utc
    validate_rows(rows)
    return sorted(
        rows,
        key=lambda row: (EXCHANGE_SORT_ORDER[row["exchange"]], row["security_code"]),
    )


def write_csv(rows: list[dict[str, str]], output_path: Path, encoding: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch all current A-share securities into a provenance-rich CSV file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV output path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--sse-page-size",
        type=int,
        default=5000,
        help="SSE page size. Default fetches each SSE board in one request.",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.05,
        help="Pause between provider pages to reduce request pressure.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding. Default: utf-8-sig for Excel compatibility.",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Skip writing the dated immutable snapshot copy (ADR-0001).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.sse_page_size <= 0:
        raise FetchError("--sse-page-size must be positive")

    retrieved_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    rows = []
    rows.extend(fetch_sse_rows(page_size=args.sse_page_size, timeout=args.timeout))
    rows.extend(fetch_szse_rows(timeout=args.timeout, pause_seconds=args.pause_seconds))
    rows.extend(fetch_bse_rows(timeout=args.timeout, pause_seconds=args.pause_seconds))
    rows = finalize_rows(rows, retrieved_at_utc=retrieved_at_utc)
    write_csv(rows, args.output, args.encoding)

    # ADR-0001 / workflow §5.3：同时另存带日期的不可变快照，主路径只保留最新版。
    if not args.no_snapshot:
        snapshot_dir = args.output.parent / "snapshots"
        snapshot_name = f"{args.output.stem}_{retrieved_at_utc[:10].replace('-', '')}{args.output.suffix}"
        snapshot_path = snapshot_dir / snapshot_name
        if snapshot_path.exists():
            print(f"Snapshot already exists, left untouched (immutable): {snapshot_path}")
        else:
            write_csv(rows, snapshot_path, args.encoding)
            print(f"Wrote immutable snapshot to {snapshot_path}")

    print(f"Wrote {len(rows)} A-share securities to {args.output}")
    print(f"Source retrieved at UTC: {retrieved_at_utc}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
