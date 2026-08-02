#!/usr/bin/env python3
"""Fetch the current U.S. listed security universe to CSV.

The script combines Nasdaq Trader's public symbol directory files:
`nasdaqlisted.txt` for Nasdaq-listed securities and `otherlisted.txt` for
NYSE/NYSE American/NYSE Arca/Cboe/IEX-listed securities. It keeps the output
security-level and excludes provider test issues by default.
"""

from __future__ import annotations

import argparse
import csv
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path


NASDAQ_TRADER_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"
NASDAQ_TRADER_DEFINITIONS_URL = "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs"
DEFAULT_OUTPUT = Path("data/raw/us_securities.csv")

CSV_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "market",
    "listed_company_name",
    "security_name",
    "currency",
    "asset_type_hint",
    "is_etf",
    "is_test_issue",
    "round_lot_size",
    "financial_status",
    "cqs_symbol",
    "nasdaq_symbol",
    "source_provider",
    "source_dataset",
    "source_retrieved_at_utc",
    "source_file_created_at_raw",
    "raw_identifier",
    "source_url",
]

NASDAQ_MARKET_CATEGORY = {
    "Q": "nasdaq_global_select_market",
    "G": "nasdaq_global_market",
    "S": "nasdaq_capital_market",
}

OTHER_EXCHANGE = {
    "A": "NYSE_AMERICAN",
    "N": "NYSE",
    "P": "NYSE_ARCA",
    "Z": "CBOE_BZX",
    "V": "IEX",
}

EXCHANGE_SORT_ORDER = {
    "NASDAQ": 0,
    "NYSE": 1,
    "NYSE_AMERICAN": 2,
    "NYSE_ARCA": 3,
    "CBOE_BZX": 4,
    "IEX": 5,
}


class FetchError(RuntimeError):
    """Raised when a provider response is unavailable or structurally invalid."""


def fetch_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/plain,*/*;q=0.8",
            "Referer": NASDAQ_TRADER_DEFINITIONS_URL,
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except (OSError, urllib.error.URLError) as exc:
        raise FetchError(f"Failed to fetch {url}: {exc}") from exc


def parse_pipe_file(text: str, expected_headers: list[str]) -> tuple[list[dict[str, str]], str]:
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        raise FetchError("Symbol directory file has too few rows")

    headers = lines[0].split("|")
    if headers != expected_headers:
        raise FetchError(f"Unexpected headers: {headers!r}")

    rows: list[dict[str, str]] = []
    file_creation_time = ""
    for line in lines[1:]:
        parts = line.split("|")
        first = parts[0].strip() if parts else ""
        if first.startswith("File Creation Time:"):
            file_creation_time = first.removeprefix("File Creation Time:").strip()
            continue
        if len(parts) != len(headers):
            raise FetchError(f"Unexpected field count for row: {line!r}")
        rows.append(dict(zip(headers, (part.strip() for part in parts), strict=True)))

    if not file_creation_time:
        raise FetchError("Symbol directory file missing File Creation Time row")
    return rows, file_creation_time


def infer_asset_type_hint(security_name: str, is_etf: str) -> str:
    if is_etf == "Y":
        return "etf_or_exchange_traded_product"
    upper_name = security_name.upper()
    patterns = [
        ("right", (" RIGHT", " RIGHTS")),
        ("unit", (" UNIT", " UNITS")),
        ("warrant", (" WARRANT", " WARRANTS")),
        ("preferred", (" PREFERRED", " PFD", " DEPOSITARY SHARE", " PREFERENCE")),
        ("note", (" NOTE", " NOTES")),
        ("bond", (" BOND", " BONDS")),
    ]
    for hint, needles in patterns:
        if any(needle in upper_name for needle in needles):
            return hint
    return "equity_security"


def fetch_nasdaq_listed(timeout: int) -> tuple[list[dict[str, str]], str, str]:
    source_url = f"{NASDAQ_TRADER_BASE_URL}/nasdaqlisted.txt"
    text = fetch_text(source_url, timeout=timeout)
    rows, file_creation_time = parse_pipe_file(
        text,
        [
            "Symbol",
            "Security Name",
            "Market Category",
            "Test Issue",
            "Financial Status",
            "Round Lot Size",
            "ETF",
            "NextShares",
        ],
    )
    normalized: list[dict[str, str]] = []
    for raw in rows:
        symbol = raw["Symbol"]
        security_name = raw["Security Name"]
        normalized.append(
            {
                "security_code": symbol,
                "symbol": symbol,
                "exchange": "NASDAQ",
                "market": NASDAQ_MARKET_CATEGORY.get(raw["Market Category"], raw["Market Category"]),
                "listed_company_name": security_name,
                "security_name": security_name,
                "currency": "USD",
                "asset_type_hint": infer_asset_type_hint(security_name, raw["ETF"]),
                "is_etf": raw["ETF"],
                "is_test_issue": raw["Test Issue"],
                "round_lot_size": raw["Round Lot Size"],
                "financial_status": raw["Financial Status"],
                "cqs_symbol": "",
                "nasdaq_symbol": symbol,
                "source_provider": "Nasdaq Trader",
                "source_dataset": "nasdaqlisted",
                "source_retrieved_at_utc": "",
                "source_file_created_at_raw": file_creation_time,
                "raw_identifier": symbol,
                "source_url": source_url,
            }
        )
    return normalized, file_creation_time, source_url


def fetch_other_listed(timeout: int) -> tuple[list[dict[str, str]], str, str]:
    source_url = f"{NASDAQ_TRADER_BASE_URL}/otherlisted.txt"
    text = fetch_text(source_url, timeout=timeout)
    rows, file_creation_time = parse_pipe_file(
        text,
        [
            "ACT Symbol",
            "Security Name",
            "Exchange",
            "CQS Symbol",
            "ETF",
            "Round Lot Size",
            "Test Issue",
            "NASDAQ Symbol",
        ],
    )
    normalized: list[dict[str, str]] = []
    for raw in rows:
        symbol = raw["ACT Symbol"]
        exchange = OTHER_EXCHANGE.get(raw["Exchange"], raw["Exchange"])
        security_name = raw["Security Name"]
        normalized.append(
            {
                "security_code": symbol,
                "symbol": symbol,
                "exchange": exchange,
                "market": exchange.lower(),
                "listed_company_name": security_name,
                "security_name": security_name,
                "currency": "USD",
                "asset_type_hint": infer_asset_type_hint(security_name, raw["ETF"]),
                "is_etf": raw["ETF"],
                "is_test_issue": raw["Test Issue"],
                "round_lot_size": raw["Round Lot Size"],
                "financial_status": "",
                "cqs_symbol": raw["CQS Symbol"],
                "nasdaq_symbol": raw["NASDAQ Symbol"],
                "source_provider": "Nasdaq Trader",
                "source_dataset": "otherlisted",
                "source_retrieved_at_utc": "",
                "source_file_created_at_raw": file_creation_time,
                "raw_identifier": symbol,
                "source_url": source_url,
            }
        )
    return normalized, file_creation_time, source_url


def finalize_rows(
    rows: list[dict[str, str]],
    retrieved_at_utc: str,
    include_test_issues: bool,
    exclude_etfs: bool,
) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    for row in rows:
        if not include_test_issues and row["is_test_issue"] == "Y":
            continue
        if exclude_etfs and row["is_etf"] == "Y":
            continue
        row["source_retrieved_at_utc"] = retrieved_at_utc
        filtered.append(row)

    validate_rows(filtered)
    return sorted(
        filtered,
        key=lambda row: (EXCHANGE_SORT_ORDER.get(row["exchange"], 99), row["security_code"]),
    )


def validate_rows(rows: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []
    for row in rows:
        symbol = row["security_code"]
        if not symbol:
            raise FetchError("Blank U.S. security symbol")
        if symbol in seen:
            duplicates.append(symbol)
        seen.add(symbol)
    if duplicates:
        sample = ", ".join(duplicates[:10])
        raise FetchError(f"Duplicate U.S. security symbols detected: {sample}")


def write_csv(rows: list[dict[str, str]], output_path: Path, encoding: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch U.S. listed securities into a provenance-rich CSV file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV output path. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding. Default: utf-8-sig for Excel compatibility.",
    )
    parser.add_argument(
        "--include-test-issues",
        action="store_true",
        help="Keep Nasdaq Trader provider test issues. Default excludes them.",
    )
    parser.add_argument(
        "--exclude-etfs",
        action="store_true",
        help="Exclude rows flagged as ETFs or exchange-traded products.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    retrieved_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    rows: list[dict[str, str]] = []
    nasdaq_rows, nasdaq_created_at, _ = fetch_nasdaq_listed(timeout=args.timeout)
    other_rows, other_created_at, _ = fetch_other_listed(timeout=args.timeout)
    rows.extend(nasdaq_rows)
    rows.extend(other_rows)
    rows = finalize_rows(
        rows=rows,
        retrieved_at_utc=retrieved_at_utc,
        include_test_issues=args.include_test_issues,
        exclude_etfs=args.exclude_etfs,
    )
    write_csv(rows, args.output, args.encoding)

    print(f"Wrote {len(rows)} U.S. securities to {args.output}")
    print(f"Nasdaq file creation time raw: {nasdaq_created_at}")
    print(f"Other-listed file creation time raw: {other_created_at}")
    print(f"Source retrieved at UTC: {retrieved_at_utc}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
