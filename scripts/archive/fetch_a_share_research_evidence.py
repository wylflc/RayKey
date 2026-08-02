#!/usr/bin/env python3
"""Fetch A-share company profile and financial evidence for full-coverage screening.

The script is resumable. It reads the immutable raw A-share universe and writes
interim evidence files that later scoring scripts can consume.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_RAW = Path("data/raw/a_share_securities.csv")
DEFAULT_QUEUE = Path("data/interim/a_share_research_queue.csv")
DEFAULT_PROFILES = Path("data/interim/a_share_company_profiles.csv")
DEFAULT_FINANCIALS = Path("data/interim/a_share_financial_indicators.csv")

COMPANY_SURVEY_ENDPOINT = "https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
FINANCE_ENDPOINT = "https://datacenter.eastmoney.com/securities/api/data/get"
SCORING_MODEL_VERSION = "full_coverage_dimensional_v0.1"

QUEUE_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "board",
    "listed_company_name",
    "security_name",
    "listing_date",
    "industry",
    "research_status",
    "profile_status",
    "financial_status",
    "profile_retrieved_at_utc",
    "financial_retrieved_at_utc",
    "last_error",
    "next_action",
]

PROFILE_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "listed_company_name",
    "security_name",
    "eastmoney_security_type",
    "eastmoney_industry",
    "csrc_industry",
    "province",
    "org_name",
    "org_name_en",
    "former_name",
    "chairman",
    "president",
    "employee_count",
    "registered_capital",
    "found_date",
    "listing_date",
    "org_web",
    "org_profile",
    "business_scope",
    "source_provider",
    "source_url",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]

FINANCIAL_COLUMNS = [
    "security_code",
    "symbol",
    "exchange",
    "listed_company_name",
    "security_name",
    "latest_report_date",
    "latest_report_type",
    "latest_report_notice_date",
    "latest_annual_report_date",
    "latest_annual_report_type",
    "latest_annual_report_notice_date",
    "total_operating_revenue",
    "parent_net_profit",
    "gross_margin_pct",
    "net_margin_pct",
    "roe_weighted_pct",
    "roic_pct",
    "operating_cashflow_per_share",
    "cashflow_to_revenue_pct",
    "debt_asset_ratio_pct",
    "revenue_yoy_pct",
    "profit_yoy_pct",
    "research_expense",
    "research_expense_to_revenue_pct",
    "employee_count_finance",
    "source_provider",
    "source_urls",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]


class EvidenceFetchError(RuntimeError):
    """Raised when evidence fetching cannot proceed."""


@dataclass(frozen=True)
class FetchResult:
    profile: dict[str, str]
    financial: dict[str, str]
    queue: dict[str, str]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise EvidenceFetchError(f"CSV not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        if not reader.fieldnames:
            raise EvidenceFetchError(f"CSV has no header: {path}")
        return list(reader.fieldnames), rows


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_existing_by_code(path: Path, key: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    _, rows = read_csv(path)
    return {row[key]: row for row in rows if row.get(key)}


def eastmoney_code(row: dict[str, str]) -> str:
    prefix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}.get(row["exchange"])
    if prefix is None:
        raise EvidenceFetchError(f"Unsupported exchange for {row['security_code']}: {row['exchange']}")
    return f"{prefix}{row['security_code']}"


def request_json(url: str, timeout: int, retries: int) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json,text/javascript,*/*;q=0.01",
                "Referer": "https://emweb.securities.eastmoney.com/",
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip" or body.startswith(b"\x1f\x8b"):
                    body = gzip.decompress(body)
                return json.loads(body.decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise EvidenceFetchError(str(last_error))


def build_company_survey_url(row: dict[str, str]) -> str:
    params = {"code": eastmoney_code(row)}
    return f"{COMPANY_SURVEY_ENDPOINT}?{urllib.parse.urlencode(params)}"


def build_finance_url(secucode: str, report_type: str, style: str, periods: int) -> str:
    params = {
        "filter": f'(SECUCODE="{secucode}")',
        "client": "APP",
        "source": "HSF10",
        "type": report_type,
        "sty": style,
        "st": "REPORT_DATE",
        "ps": str(periods),
        "sr": "-1",
    }
    return f"{FINANCE_ENDPOINT}?{urllib.parse.urlencode(params)}"


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_float(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    return f"{number:.6f}".rstrip("0").rstrip(".")


def select_latest_annual(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        report_date = safe_str(row.get("REPORT_DATE"))
        report_type = safe_str(row.get("REPORT_TYPE"))
        report_name = safe_str(row.get("REPORT_DATE_NAME"))
        if "-12-31" in report_date or "年报" in report_type or "年报" in report_name:
            return row
    return rows[0] if rows else None


def fetch_profile(raw: dict[str, str], timeout: int, retries: int, retrieved_at: str) -> dict[str, str]:
    url = build_company_survey_url(raw)
    base = {
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "source_provider": "Eastmoney F10 CompanySurvey",
        "source_url": url,
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }
    try:
        payload = request_json(url, timeout=timeout, retries=retries)
        records = payload.get("jbzl") if isinstance(payload, dict) else None
        issue_records = payload.get("fxxg") if isinstance(payload, dict) else None
        if not isinstance(records, list) or not records:
            raise EvidenceFetchError("missing jbzl profile records")
        profile = records[0]
        issue = issue_records[0] if isinstance(issue_records, list) and issue_records else {}
        base.update(
            {
                "eastmoney_security_type": safe_str(profile.get("SECURITY_TYPE")),
                "eastmoney_industry": safe_str(profile.get("EM2016")),
                "csrc_industry": safe_str(profile.get("INDUSTRYCSRC1")),
                "province": safe_str(profile.get("PROVINCE")),
                "org_name": safe_str(profile.get("ORG_NAME")),
                "org_name_en": safe_str(profile.get("ORG_NAME_EN")),
                "former_name": safe_str(profile.get("FORMERNAME")),
                "chairman": safe_str(profile.get("CHAIRMAN")),
                "president": safe_str(profile.get("PRESIDENT")),
                "employee_count": format_float(profile.get("EMP_NUM")),
                "registered_capital": format_float(profile.get("REG_CAPITAL")),
                "found_date": safe_str(issue.get("FOUND_DATE")),
                "listing_date": safe_str(issue.get("LISTING_DATE")) or raw["listing_date"],
                "org_web": safe_str(profile.get("ORG_WEB")),
                "org_profile": " ".join(safe_str(profile.get("ORG_PROFILE")).split()),
                "business_scope": " ".join(safe_str(profile.get("BUSINESS_SCOPE")).split()),
                "fetch_status": "fetched",
            }
        )
    except Exception as exc:
        base["fetch_error"] = str(exc)[:500]
    return base


def fetch_finance_rows(secucode: str, timeout: int, retries: int, periods: int) -> tuple[list[dict[str, Any]], str]:
    url = build_finance_url(
        secucode=secucode,
        report_type="RPT_F10_FINANCE_MAINFINADATA",
        style="APP_F10_MAINFINADATA",
        periods=periods,
    )
    payload = request_json(url, timeout=timeout, retries=retries)
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("data") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise EvidenceFetchError("missing main financial rows")
    return rows, url


def fetch_income_rows(secucode: str, timeout: int, retries: int, periods: int) -> tuple[list[dict[str, Any]], str]:
    variants = [
        ("RPT_F10_FINANCE_GINCOME", "APP_F10_GINCOME"),
        ("RPT_F10_FINANCE_BINCOME", "APP_F10_BINCOME"),
        ("RPT_F10_FINANCE_SINCOME", "APP_F10_SINCOME"),
        ("RPT_F10_FINANCE_IINCOME", "APP_F10_IINCOME"),
    ]
    last_error = ""
    for report_type, style in variants:
        url = build_finance_url(secucode=secucode, report_type=report_type, style=style, periods=periods)
        try:
            payload = request_json(url, timeout=timeout, retries=retries)
            result = payload.get("result") if isinstance(payload, dict) else None
            rows = result.get("data") if isinstance(result, dict) else None
            if isinstance(rows, list) and rows:
                return rows, url
        except Exception as exc:
            last_error = str(exc)
    if last_error:
        raise EvidenceFetchError(last_error)
    return [], build_finance_url(secucode, variants[0][0], variants[0][1], periods)


def fetch_financials(raw: dict[str, str], timeout: int, retries: int, periods: int, retrieved_at: str) -> dict[str, str]:
    base = {
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "source_provider": "Eastmoney F10 Finance",
        "source_urls": "",
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }
    try:
        finance_rows, finance_url = fetch_finance_rows(raw["symbol"], timeout=timeout, retries=retries, periods=periods)
        if not finance_rows:
            raise EvidenceFetchError("empty main financial rows")
        latest = finance_rows[0]
        latest_annual = select_latest_annual(finance_rows)
        income_rows, income_url = fetch_income_rows(raw["symbol"], timeout=timeout, retries=retries, periods=periods)
        annual_income = select_latest_annual(income_rows)

        annual_revenue = safe_float(latest_annual.get("TOTALOPERATEREVE")) if latest_annual else None
        research_expense = safe_float(annual_income.get("RESEARCH_EXPENSE")) if annual_income else None
        rd_ratio = None
        if annual_revenue and research_expense is not None:
            rd_ratio = research_expense / annual_revenue * 100

        base.update(
            {
                "latest_report_date": safe_str(latest.get("REPORT_DATE")),
                "latest_report_type": safe_str(latest.get("REPORT_TYPE")),
                # 公告日=可得时点（§12.4 available_at 硬约束的数据基础）；provider 无此键时留空。
                "latest_report_notice_date": safe_str(latest.get("NOTICE_DATE") or latest.get("UPDATE_DATE")),
                "latest_annual_report_date": safe_str(latest_annual.get("REPORT_DATE")) if latest_annual else "",
                "latest_annual_report_type": safe_str(latest_annual.get("REPORT_TYPE")) if latest_annual else "",
                "latest_annual_report_notice_date": safe_str(latest_annual.get("NOTICE_DATE") or latest_annual.get("UPDATE_DATE")) if latest_annual else "",
                "total_operating_revenue": format_float(latest_annual.get("TOTALOPERATEREVE") if latest_annual else ""),
                "parent_net_profit": format_float(latest_annual.get("PARENTNETPROFIT") if latest_annual else ""),
                "gross_margin_pct": format_float(latest_annual.get("XSMLL") if latest_annual else ""),
                "net_margin_pct": format_float(latest_annual.get("XSJLL") if latest_annual else ""),
                "roe_weighted_pct": format_float(latest_annual.get("ROEJQ") if latest_annual else ""),
                "roic_pct": format_float(latest_annual.get("ROIC") if latest_annual else ""),
                "operating_cashflow_per_share": format_float(latest_annual.get("MGJYXJJE") if latest_annual else ""),
                "cashflow_to_revenue_pct": format_float(latest_annual.get("JYXJLYYSR") if latest_annual else ""),
                "debt_asset_ratio_pct": format_float(latest_annual.get("ZCFZL") if latest_annual else ""),
                "revenue_yoy_pct": format_float(latest_annual.get("TOTALOPERATEREVETZ") if latest_annual else ""),
                "profit_yoy_pct": format_float(latest_annual.get("PARENTNETPROFITTZ") if latest_annual else ""),
                "research_expense": format_float(research_expense),
                "research_expense_to_revenue_pct": format_float(rd_ratio),
                "employee_count_finance": format_float(latest_annual.get("STAFF_NUM") if latest_annual else ""),
                "source_urls": f"{finance_url};{income_url}",
                "fetch_status": "fetched",
            }
        )
    except Exception as exc:
        base["fetch_error"] = str(exc)[:500]
    return base


def build_queue_row(raw: dict[str, str], profile: dict[str, str], financial: dict[str, str]) -> dict[str, str]:
    profile_status = profile.get("fetch_status", "")
    financial_status = financial.get("fetch_status", "")
    errors = [part for part in [profile.get("fetch_error", ""), financial.get("fetch_error", "")] if part]
    if profile_status == "fetched" and financial_status == "fetched":
        research_status = "evidence_fetched"
        next_action = "score_dimensions"
    elif profile_status == "fetched" or financial_status == "fetched":
        research_status = "partial_evidence"
        next_action = "retry_missing_evidence"
    else:
        research_status = "pending_evidence"
        next_action = "retry_all_evidence"
    return {
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "board": raw["board"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "listing_date": raw["listing_date"],
        "industry": raw["industry"],
        "research_status": research_status,
        "profile_status": profile_status,
        "financial_status": financial_status,
        "profile_retrieved_at_utc": profile.get("retrieved_at_utc", ""),
        "financial_retrieved_at_utc": financial.get("retrieved_at_utc", ""),
        "last_error": " | ".join(errors),
        "next_action": next_action,
    }


def fetch_one(raw: dict[str, str], timeout: int, retries: int, periods: int) -> FetchResult:
    retrieved_at = utc_now()
    profile = fetch_profile(raw, timeout=timeout, retries=retries, retrieved_at=retrieved_at)
    financial = fetch_financials(raw, timeout=timeout, retries=retries, periods=periods, retrieved_at=retrieved_at)
    queue = build_queue_row(raw, profile, financial)
    return FetchResult(profile=profile, financial=financial, queue=queue)


def run(args: argparse.Namespace) -> tuple[int, int, int]:
    _, raw_rows = read_csv(args.raw)
    profiles_by_code = read_existing_by_code(args.profiles, "security_code")
    financials_by_code = read_existing_by_code(args.financials, "security_code")

    candidates: list[dict[str, str]] = []
    for row in raw_rows:
        code = row["security_code"]
        if not args.refresh and profiles_by_code.get(code, {}).get("fetch_status") == "fetched" and financials_by_code.get(code, {}).get("fetch_status") == "fetched":
            continue
        candidates.append(row)

    if args.limit is not None:
        candidates = candidates[: args.limit]

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_one, raw, args.timeout, args.retries, args.periods): raw
            for raw in candidates
        }
        for future in as_completed(futures):
            raw = futures[future]
            code = raw["security_code"]
            try:
                result = future.result()
            except Exception as exc:
                retrieved_at = utc_now()
                profile = {
                    "security_code": code,
                    "symbol": raw["symbol"],
                    "exchange": raw["exchange"],
                    "listed_company_name": raw["listed_company_name"],
                    "security_name": raw["security_name"],
                    "source_provider": "Eastmoney F10 CompanySurvey",
                    "source_url": build_company_survey_url(raw),
                    "retrieved_at_utc": retrieved_at,
                    "fetch_status": "error",
                    "fetch_error": str(exc)[:500],
                }
                financial = {
                    "security_code": code,
                    "symbol": raw["symbol"],
                    "exchange": raw["exchange"],
                    "listed_company_name": raw["listed_company_name"],
                    "security_name": raw["security_name"],
                    "source_provider": "Eastmoney F10 Finance",
                    "retrieved_at_utc": retrieved_at,
                    "fetch_status": "error",
                    "fetch_error": str(exc)[:500],
                }
                result = FetchResult(profile=profile, financial=financial, queue=build_queue_row(raw, profile, financial))
            profiles_by_code[code] = result.profile
            financials_by_code[code] = result.financial
            completed += 1
            if args.progress_every and completed % args.progress_every == 0:
                print(f"Fetched {completed}/{len(candidates)} evidence rows", file=sys.stderr)

    queue_rows = [
        build_queue_row(
            raw,
            profiles_by_code.get(raw["security_code"], {"fetch_status": "pending"}),
            financials_by_code.get(raw["security_code"], {"fetch_status": "pending"}),
        )
        for raw in raw_rows
    ]

    profile_rows = [profiles_by_code[code] for code in sorted(profiles_by_code)]
    financial_rows = [financials_by_code[code] for code in sorted(financials_by_code)]
    write_csv(args.queue, QUEUE_COLUMNS, queue_rows)
    write_csv(args.profiles, PROFILE_COLUMNS, profile_rows)
    write_csv(args.financials, FINANCIAL_COLUMNS, financial_rows)
    ready_count = sum(1 for row in queue_rows if row["research_status"] == "evidence_fetched")
    return len(candidates), completed, ready_count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch A-share research evidence for full-coverage moat scoring.")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--periods", type=int, default=12)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    fetched_target_count, completed_count, ready_count = run(args)
    print(f"Targeted {fetched_target_count} securities for evidence fetch")
    print(f"Completed {completed_count} fetch attempts")
    print(f"{ready_count} securities have profile and financial evidence")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
