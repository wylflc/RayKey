#!/usr/bin/env python3
"""Fetch Hong Kong company profile and financial evidence for moat screening."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_RAW = Path("data/raw/hong_kong_securities.csv")
DEFAULT_QUEUE = Path("data/interim/hong_kong_research_queue.csv")
DEFAULT_PROFILES = Path("data/interim/hong_kong_company_profiles.csv")
DEFAULT_FINANCIALS = Path("data/interim/hong_kong_financial_indicators.csv")

HKF10_ENDPOINT = "https://emweb.securities.eastmoney.com/PC_HKF10/CoreReading/PageAjax"
ETNET_IPO_ENDPOINT = "https://www.etnet.com.hk/www/eng/stocks/ci_ipo_detail.php"
ETNET_BRIEF_ENDPOINT = "https://www.etnet.com.hk/www/eng/stocks/realtime/quote_ci_brief.php"
ETNET_BASIC_ENDPOINT = "https://www.etnet.com.hk/www/eng/stocks/realtime/quote_ci_basicdata.php"

QUEUE_COLUMNS = [
    "market_type",
    "market_label",
    "security_code",
    "symbol",
    "exchange",
    "board",
    "listed_company_name",
    "security_name",
    "currency",
    "isin",
    "f10_code",
    "listing_date",
    "industry",
    "research_status",
    "profile_status",
    "financial_status",
    "retrieved_at_utc",
    "last_error",
    "next_action",
]

PROFILE_COLUMNS = [
    "market_type",
    "market_label",
    "security_code",
    "symbol",
    "exchange",
    "listed_company_name",
    "security_name",
    "currency",
    "isin",
    "f10_code",
    "company_name_cn",
    "company_name_en",
    "registered_place",
    "registered_address",
    "office_address",
    "registered_capital",
    "chairman",
    "website",
    "fiscal_year_end",
    "email",
    "employee_count",
    "phone",
    "auditor",
    "company_profile",
    "industry",
    "listing_date",
    "exchange_from_f10",
    "board_from_f10",
    "source_provider",
    "source_url",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]

FINANCIAL_COLUMNS = [
    "market_type",
    "market_label",
    "security_code",
    "symbol",
    "exchange",
    "listed_company_name",
    "security_name",
    "currency",
    "isin",
    "f10_code",
    "latest_report_context",
    "latest_report_date",
    "eps",
    "book_value_per_share",
    "operating_cashflow_per_share",
    "total_operating_revenue",
    "parent_net_profit",
    "revenue_yoy_pct",
    "profit_yoy_pct",
    "net_margin_pct",
    "roe_weighted_pct",
    "debt_asset_ratio_pct",
    "issued_shares",
    "source_provider",
    "source_url",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]


class EvidenceFetchError(RuntimeError):
    """Raised when Hong Kong evidence fetching cannot proceed."""


class TextExtractor(HTMLParser):
    """Extract visible text tokens from simple public HTML pages."""

    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = normalized_text(data)
        if text:
            self.tokens.append(text)


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


def read_existing_by_code(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    _, rows = read_csv(path)
    return {row["security_code"]: row for row in rows if row.get("security_code")}


def f10_code(row: dict[str, str]) -> str:
    code = row["security_code"].strip()
    if row.get("currency") == "RMB" and code.startswith("8") and len(code) == 5:
        return f"0{code[1:]}"
    return code


def build_url(code: str) -> str:
    return f"{HKF10_ENDPOINT}?{urllib.parse.urlencode({'code': code})}"


def etnet_quote_code(code: str) -> str:
    stripped = code.lstrip("0")
    return stripped or code


def build_etnet_ipo_url(code: str) -> str:
    return f"{ETNET_IPO_ENDPOINT}?{urllib.parse.urlencode({'code': code, 'type': 'listing'})}"


def build_etnet_brief_url(code: str) -> str:
    return f"{ETNET_BRIEF_ENDPOINT}?{urllib.parse.urlencode({'code': etnet_quote_code(code)})}"


def build_etnet_basic_url(code: str) -> str:
    return f"{ETNET_BASIC_ENDPOINT}?{urllib.parse.urlencode({'code': etnet_quote_code(code)})}"


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


def request_text(url: str, timeout: int, retries: int) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "User-Agent": "Mozilla/5.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip" or body.startswith(b"\x1f\x8b"):
                    body = gzip.decompress(body)
                return body.decode("utf-8", errors="ignore")
        except (OSError, urllib.error.URLError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
    raise EvidenceFetchError(str(last_error))


def html_tokens(html: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(html)
    return parser.tokens


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalized_text(value: Any) -> str:
    return " ".join(safe_str(value).split())


def parse_number(value: Any) -> str:
    text = safe_str(value)
    if text in {"", "--", "-", "N/A", "None"}:
        return ""
    text = text.replace(",", "").replace("%", "")
    try:
        number = float(text)
    except ValueError:
        return ""
    return f"{number:.6f}".rstrip("0").rstrip(".")


def parse_etnet_number(value: Any) -> str:
    text = safe_str(value)
    if text in {"", "--", "-", "N/A", "None"}:
        return ""
    match = re.search(r"-?[\d,]+(?:\.\d+)?", text)
    if not match:
        return ""
    number = float(match.group(0).replace(",", ""))
    if "cts" in text.lower():
        number /= 100
    return f"{number:.6f}".rstrip("0").rstrip(".")


def normalize_etnet_date(value: str) -> str:
    text = safe_str(value).replace(".", "")
    text = text.split("(")[0].strip()
    if not text or text == "--":
        return ""
    for fmt in ("%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return safe_str(value)


def token_after(tokens: list[str], label: str) -> str:
    for index, token in enumerate(tokens):
        if token == label and index + 1 < len(tokens):
            return tokens[index + 1]
    return ""


def token_between(tokens: list[str], start_label: str, end_labels: set[str]) -> list[str]:
    try:
        start_index = tokens.index(start_label) + 1
    except ValueError:
        return []
    end_index = len(tokens)
    for index in range(start_index, len(tokens)):
        if tokens[index] in end_labels:
            end_index = index
            break
    return [token for token in tokens[start_index:end_index] if token and token != "--"]


def source_join(*urls: str) -> str:
    return ";".join(dict.fromkeys(url for url in urls if url))


def profile_from_payload(raw: dict[str, str], payload: dict[str, Any], url: str, retrieved_at: str) -> dict[str, str]:
    gszl = payload.get("gszl") if isinstance(payload, dict) else None
    zqzl = payload.get("zqzl") if isinstance(payload, dict) else None
    base = {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "f10_code": f10_code(raw),
        "source_provider": "Eastmoney HKF10 CoreReading",
        "source_url": url,
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }
    if not isinstance(gszl, dict) or not gszl:
        base["fetch_error"] = "missing gszl profile object"
        return base
    zqzl = zqzl if isinstance(zqzl, dict) else {}
    base.update(
        {
            "company_name_cn": safe_str(gszl.get("gsmc")),
            "company_name_en": safe_str(gszl.get("ywmc")),
            "registered_place": safe_str(gszl.get("zcdszgjhdq")),
            "registered_address": safe_str(gszl.get("zcxxdz")),
            "office_address": safe_str(gszl.get("bgdz")),
            "registered_capital": safe_str(gszl.get("zczb")),
            "chairman": safe_str(gszl.get("dsz")),
            "website": safe_str(gszl.get("gswz")),
            "fiscal_year_end": safe_str(gszl.get("njr")),
            "email": safe_str(gszl.get("email")),
            "employee_count": parse_number(gszl.get("ygrs")),
            "phone": safe_str(gszl.get("lxdh")),
            "auditor": safe_str(gszl.get("hss")),
            "company_profile": normalized_text(gszl.get("gsjs")),
            "industry": safe_str(gszl.get("sshy")),
            "listing_date": safe_str(zqzl.get("ssrq")),
            "exchange_from_f10": safe_str(zqzl.get("ssjys")),
            "board_from_f10": safe_str(zqzl.get("ssbk")),
            "fetch_status": "fetched",
        }
    )
    return base


def financial_from_payload(raw: dict[str, str], payload: dict[str, Any], url: str, retrieved_at: str) -> dict[str, str]:
    zxzb = payload.get("zxzb") if isinstance(payload, dict) else None
    base = {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "f10_code": f10_code(raw),
        "source_provider": "Eastmoney HKF10 CoreReading",
        "source_url": url,
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }
    if not isinstance(zxzb, dict) or not zxzb:
        base["fetch_error"] = "missing zxzb financial object"
        return base
    base.update(
        {
            "latest_report_context": safe_str(zxzb.get("tqdbsm") or zxzb.get("bgrqsm")),
            "latest_report_date": "",
            "eps": parse_number(zxzb.get("mgsy")),
            "book_value_per_share": parse_number(zxzb.get("mgjzc")),
            "operating_cashflow_per_share": parse_number(zxzb.get("mgjyxjl")),
            "total_operating_revenue": parse_number(zxzb.get("yye_zx")),
            "parent_net_profit": parse_number(zxzb.get("jlr_zx")),
            "revenue_yoy_pct": parse_number(zxzb.get("yyehbzz_zx")),
            "profit_yoy_pct": parse_number(zxzb.get("jlrhbzz_zx")),
            "net_margin_pct": parse_number(zxzb.get("xsjlr_zx")),
            "roe_weighted_pct": parse_number(zxzb.get("gdqyhbl_zx")),
            "debt_asset_ratio_pct": parse_number(zxzb.get("zzchbl_zx")),
            "issued_shares": parse_number(zxzb.get("yfxgb")),
            "fetch_status": "fetched",
        }
    )
    return base


def profile_from_etnet(
    raw: dict[str, str],
    ipo_tokens: list[str],
    brief_tokens: list[str],
    ipo_url: str,
    brief_url: str,
    retrieved_at: str,
) -> dict[str, str]:
    business_nature = token_after(ipo_tokens, "Business Nature") or token_after(brief_tokens, "Business Nature")
    listing_date = (
        normalize_etnet_date(token_after(brief_tokens, "Listing Date"))
        or normalize_etnet_date(token_after(ipo_tokens, "Listing Date"))
        or normalize_etnet_date(token_after(ipo_tokens, "Dealings in Shares commence on"))
    )
    profile_parts = token_between(
        ipo_tokens,
        "COMPANY PROFILE",
        {"BASIC INFORMATION", "GLOBAL OFFERING", "TIME TABLE", "Sales Statistics (HKD)"},
    )
    company_profile = normalized_text(" ".join(profile_parts))
    if not company_profile and business_nature:
        company_profile = f"Business nature: {business_nature}."

    base = {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "f10_code": f10_code(raw),
        "company_name_cn": "",
        "company_name_en": raw["listed_company_name"],
        "registered_place": "",
        "registered_address": "",
        "office_address": token_after(brief_tokens, "Company Address"),
        "registered_capital": "",
        "chairman": token_after(brief_tokens, "Chairman"),
        "website": token_after(brief_tokens, "Website"),
        "fiscal_year_end": token_after(brief_tokens, "Financial Year (DD/MM)") or token_after(brief_tokens, "Financial Year (D/M)"),
        "email": token_after(brief_tokens, "Email Address"),
        "employee_count": "",
        "phone": token_after(brief_tokens, "Tel No"),
        "auditor": token_after(brief_tokens, "Auditors"),
        "company_profile": company_profile,
        "industry": business_nature,
        "listing_date": listing_date,
        "exchange_from_f10": "Hong Kong (Main Board)" if "Hong Kong (Main Board)" in ipo_tokens else "",
        "board_from_f10": "Main Board" if "Hong Kong (Main Board)" in ipo_tokens else "",
        "source_provider": "ETNet Company Information",
        "source_url": source_join(ipo_url, brief_url),
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "fetched" if company_profile or business_nature else "error",
        "fetch_error": "" if company_profile or business_nature else "missing ETNet company profile fields",
    }
    return base


def financial_from_etnet(
    raw: dict[str, str],
    basic_tokens: list[str],
    basic_url: str,
    retrieved_at: str,
) -> dict[str, str]:
    eps = parse_etnet_number(token_after(basic_tokens, "EPS (RMB)") or token_after(basic_tokens, "EPS (HKD)") or token_after(basic_tokens, "EPS"))
    cashflow = parse_etnet_number(token_after(basic_tokens, "Cashflowper Share ($)") or token_after(basic_tokens, "Cashflow per Share ($)"))
    book_value = parse_etnet_number(token_after(basic_tokens, "BNV (RMB)") or token_after(basic_tokens, "BNV (HKD)") or token_after(basic_tokens, "BNV"))
    issued_shares = parse_etnet_number(token_after(basic_tokens, "Issued Share Capital"))
    report_context = token_after(basic_tokens, "Year (Currency)")
    fetched = bool(eps or cashflow or book_value or issued_shares or report_context)
    return {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "f10_code": f10_code(raw),
        "latest_report_context": report_context,
        "latest_report_date": "",
        "eps": eps,
        "book_value_per_share": book_value,
        "operating_cashflow_per_share": cashflow,
        "total_operating_revenue": "",
        "parent_net_profit": "",
        "revenue_yoy_pct": "",
        "profit_yoy_pct": "",
        "net_margin_pct": "",
        "roe_weighted_pct": "",
        "debt_asset_ratio_pct": "",
        "issued_shares": issued_shares,
        "source_provider": "ETNet Basic Data",
        "source_url": basic_url,
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "fetched" if fetched else "error",
        "fetch_error": "" if fetched else "missing ETNet financial fields",
    }


def etnet_fallback(raw: dict[str, str], timeout: int, retries: int, retrieved_at: str) -> tuple[dict[str, str], dict[str, str]]:
    code = f10_code(raw)
    ipo_url = build_etnet_ipo_url(code)
    brief_url = build_etnet_brief_url(code)
    basic_url = build_etnet_basic_url(code)
    errors: list[str] = []
    try:
        ipo_tokens = html_tokens(request_text(ipo_url, timeout=timeout, retries=retries))
    except Exception as exc:
        ipo_tokens = []
        errors.append(f"ETNet IPO: {exc}")
    try:
        brief_tokens = html_tokens(request_text(brief_url, timeout=timeout, retries=retries))
    except Exception as exc:
        brief_tokens = []
        errors.append(f"ETNet brief: {exc}")
    try:
        basic_tokens = html_tokens(request_text(basic_url, timeout=timeout, retries=retries))
    except Exception as exc:
        basic_tokens = []
        errors.append(f"ETNet basic: {exc}")

    profile = profile_from_etnet(raw, ipo_tokens, brief_tokens, ipo_url, brief_url, retrieved_at)
    financial = financial_from_etnet(raw, basic_tokens, basic_url, retrieved_at)
    if errors:
        if profile["fetch_status"] != "fetched":
            profile["fetch_error"] = " | ".join([profile.get("fetch_error", ""), *errors]).strip(" |")
        if financial["fetch_status"] != "fetched":
            financial["fetch_error"] = " | ".join([financial.get("fetch_error", ""), *errors]).strip(" |")
    return profile, financial


def build_queue_row(raw: dict[str, str], profile: dict[str, str], financial: dict[str, str]) -> dict[str, str]:
    profile_status = profile.get("fetch_status", "")
    financial_status = financial.get("fetch_status", "")
    errors = [part for part in [profile.get("fetch_error", ""), financial.get("fetch_error", "")] if part]
    if profile_status == "fetched" and financial_status == "fetched":
        research_status = "evidence_fetched"
        next_action = "score_dimensions"
    elif profile_status == "fetched" or financial_status == "fetched":
        research_status = "partial_evidence"
        next_action = "retry_missing_evidence_or_score_low_confidence"
    else:
        research_status = "pending_evidence"
        next_action = "retry_all_evidence"
    return {
        "market_type": "HONG_KONG",
        "market_label": "港股",
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "board": raw["board"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw.get("currency", ""),
        "isin": raw.get("isin", ""),
        "f10_code": f10_code(raw),
        "listing_date": profile.get("listing_date", ""),
        "industry": profile.get("industry", ""),
        "research_status": research_status,
        "profile_status": profile_status,
        "financial_status": financial_status,
        "retrieved_at_utc": profile.get("retrieved_at_utc") or financial.get("retrieved_at_utc", ""),
        "last_error": " | ".join(errors),
        "next_action": next_action,
    }


def fetch_one(raw: dict[str, str], timeout: int, retries: int) -> FetchResult:
    retrieved_at = utc_now()
    code = f10_code(raw)
    url = build_url(code)
    try:
        payload = request_json(url, timeout=timeout, retries=retries)
        profile = profile_from_payload(raw, payload, url, retrieved_at)
        financial = financial_from_payload(raw, payload, url, retrieved_at)
        if profile["fetch_status"] != "fetched" or financial["fetch_status"] != "fetched":
            fallback_profile, fallback_financial = etnet_fallback(raw, timeout=timeout, retries=retries, retrieved_at=retrieved_at)
            if profile["fetch_status"] != "fetched" and fallback_profile["fetch_status"] == "fetched":
                profile = fallback_profile
            if financial["fetch_status"] != "fetched" and fallback_financial["fetch_status"] == "fetched":
                financial = fallback_financial
    except Exception as exc:
        error = str(exc)[:500]
        profile = profile_from_payload(raw, {}, url, retrieved_at)
        financial = financial_from_payload(raw, {}, url, retrieved_at)
        profile["fetch_error"] = error
        financial["fetch_error"] = error
        fallback_profile, fallback_financial = etnet_fallback(raw, timeout=timeout, retries=retries, retrieved_at=retrieved_at)
        if fallback_profile["fetch_status"] == "fetched":
            profile = fallback_profile
        if fallback_financial["fetch_status"] == "fetched":
            financial = fallback_financial
    return FetchResult(profile=profile, financial=financial, queue=build_queue_row(raw, profile, financial))


def run(args: argparse.Namespace) -> tuple[int, int, int]:
    _, raw_rows = read_csv(args.raw)
    profiles_by_code = read_existing_by_code(args.profiles)
    financials_by_code = read_existing_by_code(args.financials)
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
        futures = {executor.submit(fetch_one, raw, args.timeout, args.retries): raw for raw in candidates}
        for future in as_completed(futures):
            raw = futures[future]
            result = future.result()
            profiles_by_code[raw["security_code"]] = result.profile
            financials_by_code[raw["security_code"]] = result.financial
            completed += 1
            if args.progress_every and completed % args.progress_every == 0:
                print(f"Fetched {completed}/{len(candidates)} Hong Kong evidence rows", file=sys.stderr)

    queue_rows = [
        build_queue_row(
            raw,
            profiles_by_code.get(raw["security_code"], {"fetch_status": "pending"}),
            financials_by_code.get(raw["security_code"], {"fetch_status": "pending"}),
        )
        for raw in raw_rows
    ]
    write_csv(args.queue, QUEUE_COLUMNS, queue_rows)
    write_csv(args.profiles, PROFILE_COLUMNS, [profiles_by_code[code] for code in sorted(profiles_by_code)])
    write_csv(args.financials, FINANCIAL_COLUMNS, [financials_by_code[code] for code in sorted(financials_by_code)])
    ready_count = sum(1 for row in queue_rows if row["research_status"] == "evidence_fetched")
    return len(candidates), completed, ready_count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Hong Kong research evidence for full-coverage moat scoring.")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--progress-every", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    targeted_count, completed_count, ready_count = run(args)
    print(f"Targeted {targeted_count} Hong Kong securities for evidence fetch")
    print(f"Completed {completed_count} fetch attempts")
    print(f"{ready_count} Hong Kong securities have profile and financial evidence")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
