#!/usr/bin/env python3
"""Fetch the current Hong Kong listed equity security universe to CSV.

The script reads HKEX's public "Full List of Securities" workbook and keeps
only equity rows. The output is security-level: multiple counters or share
classes for the same listed company remain separate securities.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


HKEX_SECURITIES_LIST_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
HKEX_SECURITIES_LIST_PAGE = "https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en"
DEFAULT_OUTPUT = Path("data/raw/hong_kong_securities.csv")

SPREADSHEET_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

CSV_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "board",
    "listed_company_name",
    "security_name",
    "currency",
    "isin",
    "category",
    "sub_category",
    "board_lot",
    "subject_to_stamp_duty",
    "shortsell_eligible",
    "cas_eligible",
    "vcm_eligible",
    "admitted_to_ccass",
    "pos_eligible",
    "rmb_counter",
    "source_provider",
    "source_dataset",
    "source_retrieved_at_utc",
    "source_as_of_date",
    "raw_identifier",
    "source_url",
]

BOARD_BY_SUB_CATEGORY = {
    "Equity Securities (Main Board)": "main_board",
    "Equity Securities (GEM)": "gem",
    "Investment Companies": "investment_companies",
    "Trading Only Securities": "trading_only",
    "Depositary Receipts": "depositary_receipts",
}


class FetchError(RuntimeError):
    """Raised when a provider response is unavailable or structurally invalid."""


def fetch_bytes(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*;q=0.8",
            "Referer": HKEX_SECURITIES_LIST_PAGE,
            "User-Agent": "Mozilla/5.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise FetchError(f"Failed to fetch {url}: {exc}") from exc


def load_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    root = ElementTree.fromstring(workbook.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for item in root.findall("x:si", SPREADSHEET_NS):
        parts = [node.text or "" for node in item.findall(".//x:t", SPREADSHEET_NS)]
        strings.append("".join(parts))
    return strings


def column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref)
    if not match:
        raise FetchError(f"Unexpected cell reference: {cell_ref!r}")
    index = 0
    for char in match.group(1):
        index = index * 26 + ord(char) - ord("A") + 1
    return index


def cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    value_type = cell.attrib.get("t")
    value = cell.find("x:v", SPREADSHEET_NS)
    inline = cell.find("x:is", SPREADSHEET_NS)

    if value_type == "s" and value is not None and value.text is not None:
        return shared_strings[int(value.text)]
    if value_type == "inlineStr" and inline is not None:
        return "".join(node.text or "" for node in inline.findall(".//x:t", SPREADSHEET_NS))
    if value is not None and value.text is not None:
        return value.text
    return ""


def parse_first_worksheet(xlsx_bytes: bytes) -> list[dict[int, str]]:
    try:
        workbook = zipfile.ZipFile(BytesIO(xlsx_bytes))
    except zipfile.BadZipFile as exc:
        raise FetchError(f"HKEX download is not a valid XLSX file: {exc}") from exc

    worksheet_name = "xl/worksheets/sheet1.xml"
    if worksheet_name not in workbook.namelist():
        raise FetchError("HKEX workbook missing xl/worksheets/sheet1.xml")

    shared_strings = load_shared_strings(workbook)
    root = ElementTree.fromstring(workbook.read(worksheet_name))
    rows: list[dict[int, str]] = []
    for row in root.findall(".//x:row", SPREADSHEET_NS):
        values: dict[int, str] = {}
        for cell in row.findall("x:c", SPREADSHEET_NS):
            cell_ref = cell.attrib.get("r", "")
            values[column_index(cell_ref)] = cell_value(cell, shared_strings).strip()
        rows.append(values)
    return rows


def parse_as_of_date(title: str) -> str:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", title)
    if not match:
        return ""
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def header_map(header_row: dict[int, str]) -> dict[str, int]:
    mapping = {value: index for index, value in header_row.items() if value}
    required = {
        "Stock Code",
        "Name of Securities",
        "Category",
        "Sub-Category",
        "Board Lot",
        "ISIN",
        "Subject to Stamp Duty",
        "Shortsell Eligible",
        "CAS Eligible",
        "VCM Eligible",
        "Admitted to CCASS",
        "POS Eligible",
        "Trading Currency",
        "RMB Counter",
    }
    missing = sorted(required - set(mapping))
    if missing:
        raise FetchError(f"HKEX workbook missing expected columns: {', '.join(missing)}")
    return mapping


def normalize_flag(value: str) -> str:
    return "Y" if value.strip().upper() == "Y" else ""


def normalize_board(sub_category: str) -> str:
    return BOARD_BY_SUB_CATEGORY.get(sub_category, sub_category.lower().replace(" ", "_") or "unknown")


def normalize_board_lot(value: str) -> str:
    return value.replace(",", "")


def normalize_rows(rows: list[dict[int, str]], retrieved_at_utc: str) -> list[dict[str, str]]:
    if len(rows) < 4:
        raise FetchError("HKEX workbook has too few rows")

    source_as_of_date = parse_as_of_date(rows[1].get(1, ""))
    columns = header_map(rows[2])
    normalized: list[dict[str, str]] = []

    for raw in rows[3:]:
        category = raw.get(columns["Category"], "").strip()
        if category != "Equity":
            continue

        code = raw.get(columns["Stock Code"], "").strip()
        name = raw.get(columns["Name of Securities"], "").strip()
        if not code or not name:
            continue
        if not code.isdigit():
            raise FetchError(f"Unexpected HKEX stock code: {code!r}")

        sub_category = raw.get(columns["Sub-Category"], "").strip()
        currency = raw.get(columns["Trading Currency"], "").strip()
        normalized.append(
            {
                "security_code": code,
                "symbol": f"{code}.HK",
                "exchange": "HKEX",
                "board": normalize_board(sub_category),
                "listed_company_name": name,
                "security_name": name,
                "currency": currency,
                "isin": raw.get(columns["ISIN"], "").strip(),
                "category": category,
                "sub_category": sub_category,
                "board_lot": normalize_board_lot(raw.get(columns["Board Lot"], "").strip()),
                "subject_to_stamp_duty": normalize_flag(raw.get(columns["Subject to Stamp Duty"], "")),
                "shortsell_eligible": normalize_flag(raw.get(columns["Shortsell Eligible"], "")),
                "cas_eligible": normalize_flag(raw.get(columns["CAS Eligible"], "")),
                "vcm_eligible": normalize_flag(raw.get(columns["VCM Eligible"], "")),
                "admitted_to_ccass": normalize_flag(raw.get(columns["Admitted to CCASS"], "")),
                "pos_eligible": normalize_flag(raw.get(columns["POS Eligible"], "")),
                "rmb_counter": raw.get(columns["RMB Counter"], "").strip(),
                "source_provider": "Hong Kong Exchanges and Clearing Limited",
                "source_dataset": "hkex_full_list_of_securities_equity",
                "source_retrieved_at_utc": retrieved_at_utc,
                "source_as_of_date": source_as_of_date,
                "raw_identifier": code,
                "source_url": HKEX_SECURITIES_LIST_URL,
            }
        )

    validate_rows(normalized)
    return sorted(normalized, key=lambda row: (row["security_code"], row["currency"], row["isin"]))


def validate_rows(rows: list[dict[str, str]]) -> None:
    seen: set[tuple[str, str]] = set()
    duplicates: list[str] = []
    for row in rows:
        code = row["security_code"]
        currency = row["currency"]
        if len(code) != 5 or not code.isdigit():
            raise FetchError(f"Unexpected HKEX stock code: {code!r}")
        key = (code, currency)
        if key in seen:
            duplicates.append(f"{code}/{currency}")
        seen.add(key)
    if duplicates:
        sample = ", ".join(duplicates[:10])
        raise FetchError(f"Duplicate security_code/currency values detected: {sample}")


def write_csv(rows: list[dict[str, str]], output_path: Path, encoding: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_summary(rows: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["board"]] = counts.get(row["board"], 0) + 1
    return json.dumps(counts, ensure_ascii=False, sort_keys=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Hong Kong listed equity securities into a provenance-rich CSV file.",
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    retrieved_at_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    xlsx_bytes = fetch_bytes(HKEX_SECURITIES_LIST_URL, timeout=args.timeout)
    worksheet_rows = parse_first_worksheet(xlsx_bytes)
    rows = normalize_rows(worksheet_rows, retrieved_at_utc=retrieved_at_utc)
    write_csv(rows, args.output, args.encoding)

    print(f"Wrote {len(rows)} Hong Kong equity securities to {args.output}")
    print(f"Board counts: {write_summary(rows)}")
    print(f"Source retrieved at UTC: {retrieved_at_utc}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
