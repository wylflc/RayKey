#!/usr/bin/env python3
"""Fetch U.S. company profile and financial evidence for moat screening."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_RAW = Path("data/raw/us_securities.csv")
DEFAULT_QUEUE = Path("data/interim/us_research_queue.csv")
DEFAULT_PROFILES = Path("data/interim/us_company_profiles.csv")
DEFAULT_FINANCIALS = Path("data/interim/us_financial_indicators.csv")

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_BROWSE_COMPANY_URL = "https://www.sec.gov/edgar/browse/?CIK={cik:010d}"

MARKET_TYPE = "USA"
MARKET_LABEL = "美股"
DEFAULT_USER_AGENT = "AShareQuant research workflow contact@example.com"
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}

QUEUE_COLUMNS = [
    "market_type",
    "market_label",
    "security_code",
    "symbol",
    "exchange",
    "market",
    "listed_company_name",
    "security_name",
    "currency",
    "asset_type_hint",
    "is_etf",
    "sec_cik",
    "sec_ticker",
    "security_eligibility",
    "security_eligibility_reason",
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
    "market",
    "listed_company_name",
    "security_name",
    "currency",
    "asset_type_hint",
    "is_etf",
    "sec_cik",
    "sec_ticker",
    "sec_company_name",
    "entity_type",
    "sic",
    "sic_description",
    "owner_org",
    "fiscal_year_end",
    "state_of_incorporation",
    "state_of_incorporation_description",
    "description",
    "website",
    "investor_website",
    "latest_annual_form",
    "latest_annual_report_date",
    "latest_annual_filing_date",
    "latest_annual_accession",
    "latest_annual_primary_doc",
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
    "market",
    "listed_company_name",
    "security_name",
    "currency",
    "asset_type_hint",
    "is_etf",
    "sec_cik",
    "sec_ticker",
    "latest_report_context",
    "latest_report_end_date",
    "latest_filed_date",
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "assets",
    "liabilities",
    "stockholders_equity",
    "research_and_development_expense",
    "eps_diluted",
    "shares_outstanding",
    "weighted_avg_diluted_shares",
    "revenue_yoy_pct",
    "net_income_yoy_pct",
    "gross_margin_pct",
    "operating_margin_pct",
    "net_margin_pct",
    "roe_pct",
    "debt_asset_ratio_pct",
    "operating_cashflow_to_revenue_pct",
    "rd_to_revenue_pct",
    "source_provider",
    "source_url",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]


class EvidenceFetchError(RuntimeError):
    """Raised when U.S. evidence fetching cannot proceed."""


@dataclass(frozen=True)
class CikMatch:
    cik: int
    ticker: str
    company_name: str
    exchange: str


@dataclass(frozen=True)
class MetricValue:
    value: float
    end: str
    filed: str
    form: str
    fy: str
    fp: str
    taxonomy: str
    tag: str
    unit: str


@dataclass(frozen=True)
class FetchResult:
    profile: dict[str, str]
    financial: dict[str, str]
    queue: dict[str, str]


SEC_REQUEST_LOCK = threading.Lock()
SEC_LAST_REQUEST_AT = 0.0


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


def rate_limit(min_interval: float) -> None:
    global SEC_LAST_REQUEST_AT
    if min_interval <= 0:
        return
    with SEC_REQUEST_LOCK:
        elapsed = time.monotonic() - SEC_LAST_REQUEST_AT
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        SEC_LAST_REQUEST_AT = time.monotonic()


def request_json(url: str, timeout: int, retries: int, user_agent: str, min_interval: float) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        rate_limit(min_interval)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 404:
                break
            if attempt < retries:
                time.sleep(0.75 * (attempt + 1))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.75 * (attempt + 1))
    raise EvidenceFetchError(str(last_error))


def safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalized_text(value: Any) -> str:
    return " ".join(safe_str(value).split())


def fmt_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def pct_change(current: float | None, previous: float | None) -> str:
    if current is None or previous in (None, 0):
        return ""
    return fmt_number((current - previous) / abs(previous) * 100)


def ratio_pct(numerator: float | None, denominator: float | None) -> str:
    if numerator is None or denominator in (None, 0):
        return ""
    return fmt_number(numerator / denominator * 100)


def source_join(*urls: str) -> str:
    return ";".join(dict.fromkeys(url for url in urls if url))


def ticker_key(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", symbol.upper())


def sec_source_url(cik: int) -> str:
    return SEC_BROWSE_COMPANY_URL.format(cik=cik)


def load_cik_map(timeout: int, retries: int, user_agent: str, min_interval: float) -> dict[str, CikMatch]:
    mapping: dict[str, CikMatch] = {}

    exchange_payload = request_json(SEC_COMPANY_TICKERS_EXCHANGE_URL, timeout, retries, user_agent, min_interval)
    fields = exchange_payload.get("fields", [])
    data = exchange_payload.get("data", [])
    field_index = {name: index for index, name in enumerate(fields)}
    for item in data:
        ticker = safe_str(item[field_index["ticker"]]).upper()
        match = CikMatch(
            cik=int(item[field_index["cik"]]),
            ticker=ticker,
            company_name=safe_str(item[field_index["name"]]),
            exchange=safe_str(item[field_index["exchange"]]),
        )
        mapping[ticker] = match
        mapping.setdefault(ticker_key(ticker), match)

    plain_payload = request_json(SEC_COMPANY_TICKERS_URL, timeout, retries, user_agent, min_interval)
    for item in plain_payload.values():
        ticker = safe_str(item.get("ticker")).upper()
        if not ticker:
            continue
        match = CikMatch(
            cik=int(item["cik_str"]),
            ticker=ticker,
            company_name=safe_str(item.get("title")),
            exchange="",
        )
        mapping.setdefault(ticker, match)
        mapping.setdefault(ticker_key(ticker), match)
    return mapping


def cik_for_row(row: dict[str, str], cik_map: dict[str, CikMatch]) -> CikMatch | None:
    symbol = row["symbol"].upper()
    return cik_map.get(symbol) or cik_map.get(ticker_key(symbol))


def security_eligibility(row: dict[str, str]) -> tuple[str, str]:
    name = row["security_name"].upper()
    symbol = row["symbol"].upper()
    if row.get("is_etf") == "Y":
        return "not_eligible_fund_or_etp", "Nasdaq Trader marks the security as an ETF or exchange-traded product."
    if "$" in symbol or symbol.endswith((".W", ".U", ".R")):
        return "not_eligible_non_common_security", "Symbol suffix indicates a warrant, unit, right, preferred, or other non-common-equity instrument."
    non_company_terms = [
        " ETF",
        " ETN",
        " EXCHANGE TRADED",
        " INDEX",
        " WARRANT",
        " WARRANTS",
        " RIGHT",
        " RIGHTS",
        " UNIT",
        " UNITS",
        " PREFERRED",
        " PREFERENCE",
        " PFD",
        " PRD",
        " PFD SER",
        " PREFERRED STOCK",
        " DEBENTURE",
        " NOTE",
        " NOTES",
        " BOND",
        " BONDS",
        " BABY BOND",
        " TRUST VI",
        " TRUST VII",
        " TRUST SHARES",
        " CLOSED-END",
        " CLOSED END",
        " FUND",
        " TERM TRUST",
        " INCOME TRUST",
        " MUNICIPAL",
        " FLOATING RATE",
        " 2X ",
        " 3X ",
        " BEAR ",
        " BULL ",
        " INVERSE ",
        " LEVERAGED ",
    ]
    fund_like_trust_terms = [
        "BLACKROCK",
        "NUVEEN",
        "ABRDN",
        "INVESCO",
        "EATON VANCE",
        "PIMCO",
        "GABELLI",
        "CALAMOS",
        "MFS",
        "ALLSPRING",
        "WESTERN ASSET",
        "JOHN HANCOCK",
        "NEUBERGER",
        "DOUBLELINE",
        "CLOUGH",
        "COHEN & STEERS",
        "TEKLA",
        "VIRTUS",
        "TORTOISE",
    ]
    if " TRUST" in name and any(term in name for term in fund_like_trust_terms):
        return "not_eligible_non_common_security", "Security name indicates a closed-end fund or investment trust rather than an operating listed company."
    if ("DEPOSITARY SH" in name or "DEP SHS" in name) and not any(term in name for term in ["AMERICAN DEPOSITAR", "PREFERRED", "PREFERENCE", " PFD", " PRD"]):
        return "eligible_common_equity", "Depositary share represents common equity or ADS rather than preferred stock."
    if any(security_name_has_term(name, term) for term in non_company_terms):
        return "not_eligible_non_common_security", "Security name indicates a fund, derivative, unit, preferred share, note, or other non-common-equity instrument."
    return "eligible_common_equity", "Common equity, ordinary share, ADS, or similar listed-company security."


def security_name_has_term(name: str, term: str) -> bool:
    phrase = term.strip()
    if not phrase:
        return False
    pattern = r"(?<![A-Z0-9])" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?![A-Z0-9])"
    return re.search(pattern, name) is not None


def latest_annual_filing(submission: dict[str, Any]) -> dict[str, str]:
    recent = submission.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    report_dates = recent.get("reportDate", [])
    filing_dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    candidates: list[dict[str, str]] = []
    for index, form in enumerate(forms):
        if form not in ANNUAL_FORMS:
            continue
        candidates.append(
            {
                "latest_annual_form": safe_str(form),
                "latest_annual_report_date": safe_str(report_dates[index] if index < len(report_dates) else ""),
                "latest_annual_filing_date": safe_str(filing_dates[index] if index < len(filing_dates) else ""),
                "latest_annual_accession": safe_str(accessions[index] if index < len(accessions) else ""),
                "latest_annual_primary_doc": safe_str(docs[index] if index < len(docs) else ""),
            }
        )
    candidates.sort(key=lambda row: (row["latest_annual_report_date"], row["latest_annual_filing_date"]), reverse=True)
    return candidates[0] if candidates else {}


def base_profile(raw: dict[str, str], match: CikMatch | None, retrieved_at: str) -> dict[str, str]:
    return {
        "market_type": MARKET_TYPE,
        "market_label": MARKET_LABEL,
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "market": raw["market"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw["currency"],
        "asset_type_hint": raw.get("asset_type_hint", ""),
        "is_etf": raw.get("is_etf", ""),
        "sec_cik": str(match.cik) if match else "",
        "sec_ticker": match.ticker if match else "",
        "source_provider": "SEC EDGAR",
        "source_url": sec_source_url(match.cik) if match else raw.get("source_url", ""),
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }


def base_financial(raw: dict[str, str], match: CikMatch | None, retrieved_at: str) -> dict[str, str]:
    return {
        "market_type": MARKET_TYPE,
        "market_label": MARKET_LABEL,
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "market": raw["market"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw["currency"],
        "asset_type_hint": raw.get("asset_type_hint", ""),
        "is_etf": raw.get("is_etf", ""),
        "sec_cik": str(match.cik) if match else "",
        "sec_ticker": match.ticker if match else "",
        "source_provider": "SEC EDGAR companyfacts",
        "source_url": SEC_COMPANYFACTS_URL.format(cik=match.cik) if match else raw.get("source_url", ""),
        "retrieved_at_utc": retrieved_at,
        "fetch_status": "error",
        "fetch_error": "",
    }


def not_applicable_rows(raw: dict[str, str], eligibility: str, reason: str, retrieved_at: str) -> FetchResult:
    profile = base_profile(raw, None, retrieved_at)
    profile.update(
        {
            "source_provider": "Nasdaq Trader",
            "source_url": raw.get("source_url", ""),
            "fetch_status": "not_applicable",
            "fetch_error": reason,
        }
    )
    financial = base_financial(raw, None, retrieved_at)
    financial.update(
        {
            "source_provider": "Nasdaq Trader",
            "source_url": raw.get("source_url", ""),
            "fetch_status": "not_applicable",
            "fetch_error": reason,
        }
    )
    queue = build_queue_row(raw, profile, financial, eligibility, reason)
    return FetchResult(profile=profile, financial=financial, queue=queue)


def raw_fallback_rows(raw: dict[str, str], eligibility: str, reason: str, retrieved_at: str, error: str) -> FetchResult:
    profile = base_profile(raw, None, retrieved_at)
    profile.update(
        {
            "sec_company_name": raw["listed_company_name"],
            "description": raw["security_name"],
            "source_provider": "Nasdaq Trader",
            "source_url": raw.get("source_url", ""),
            "fetch_status": "fetched",
            "fetch_error": error,
        }
    )
    financial = base_financial(raw, None, retrieved_at)
    financial.update(
        {
            "source_provider": "Nasdaq Trader",
            "source_url": raw.get("source_url", ""),
            "fetch_status": "not_available",
            "fetch_error": error,
        }
    )
    return FetchResult(profile=profile, financial=financial, queue=build_queue_row(raw, profile, financial, eligibility, reason))


def pending_rows(raw: dict[str, str], eligibility: str, reason: str, retrieved_at: str, error: str) -> FetchResult:
    profile = base_profile(raw, None, retrieved_at)
    profile.update(
        {
            "source_provider": "",
            "source_url": "",
            "fetch_status": "pending",
            "fetch_error": error,
        }
    )
    financial = base_financial(raw, None, retrieved_at)
    financial.update(
        {
            "source_provider": "",
            "source_url": "",
            "fetch_status": "pending",
            "fetch_error": error,
        }
    )
    return FetchResult(profile=profile, financial=financial, queue=build_queue_row(raw, profile, financial, eligibility, reason))


def profile_from_submission(raw: dict[str, str], match: CikMatch, submission: dict[str, Any], retrieved_at: str) -> dict[str, str]:
    profile = base_profile(raw, match, retrieved_at)
    annual = latest_annual_filing(submission)
    addresses = submission.get("addresses", {})
    business_address = addresses.get("business", {}) if isinstance(addresses, dict) else {}
    description = normalized_text(submission.get("description"))
    if not description:
        parts = [safe_str(submission.get("sicDescription")), safe_str(submission.get("category")), safe_str(submission.get("entityType"))]
        description = normalized_text(" ".join(part for part in parts if part))
    profile.update(
        {
            "sec_company_name": safe_str(submission.get("name")) or match.company_name,
            "entity_type": safe_str(submission.get("entityType")),
            "sic": safe_str(submission.get("sic")),
            "sic_description": safe_str(submission.get("sicDescription")),
            "owner_org": safe_str(submission.get("ownerOrg")),
            "fiscal_year_end": safe_str(submission.get("fiscalYearEnd")),
            "state_of_incorporation": safe_str(submission.get("stateOfIncorporation")),
            "state_of_incorporation_description": safe_str(submission.get("stateOfIncorporationDescription")),
            "description": description,
            "website": safe_str(submission.get("website")),
            "investor_website": safe_str(submission.get("investorWebsite")),
            "fetch_status": "fetched",
        }
    )
    profile.update(annual)
    if business_address:
        city = safe_str(business_address.get("city"))
        state = safe_str(business_address.get("stateOrCountryDescription") or business_address.get("stateOrCountry"))
        profile["description"] = normalized_text(f"{profile['description']} Business address: {city} {state}".strip())
    return profile


FLOW_TAGS = {
    "revenue": [
        ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
        ("us-gaap", "Revenues"),
        ("us-gaap", "SalesRevenueNet"),
        ("us-gaap", "SalesRevenueGoodsNet"),
        ("us-gaap", "SalesRevenueServicesNet"),
        ("us-gaap", "InterestAndDividendIncomeOperating"),
        ("ifrs-full", "Revenue"),
    ],
    "gross_profit": [("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")],
    "operating_income": [("us-gaap", "OperatingIncomeLoss"), ("ifrs-full", "ProfitLossFromOperatingActivities")],
    "net_income": [
        ("us-gaap", "NetIncomeLoss"),
        ("us-gaap", "ProfitLoss"),
        ("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic"),
        ("ifrs-full", "ProfitLoss"),
    ],
    "operating_cash_flow": [
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
        ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ("ifrs-full", "CashFlowsFromUsedInOperatingActivities"),
    ],
    "research_and_development_expense": [
        ("us-gaap", "ResearchAndDevelopmentExpense"),
        ("us-gaap", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
        ("ifrs-full", "ResearchAndDevelopmentExpense"),
    ],
    "eps_diluted": [("us-gaap", "EarningsPerShareDiluted"), ("ifrs-full", "DilutedEarningsLossPerShare")],
    "weighted_avg_diluted_shares": [
        ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding"),
        ("ifrs-full", "WeightedAverageNumberOfDilutedSharesOutstanding"),
    ],
}

BALANCE_TAGS = {
    "assets": [("us-gaap", "Assets"), ("ifrs-full", "Assets")],
    "liabilities": [("us-gaap", "Liabilities"), ("ifrs-full", "Liabilities")],
    "stockholders_equity": [
        ("us-gaap", "StockholdersEquity"),
        ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ("ifrs-full", "Equity"),
    ],
    "shares_outstanding": [("dei", "EntityCommonStockSharesOutstanding")],
}


def parse_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:10])
    except ValueError:
        return None


def fact_duration_days(item: dict[str, Any]) -> int | None:
    start = parse_date(safe_str(item.get("start")))
    end = parse_date(safe_str(item.get("end")))
    if not start or not end:
        return None
    return (end - start).days


def metric_series(facts: dict[str, Any], candidates: list[tuple[str, str]], flow: bool) -> list[MetricValue]:
    values: list[MetricValue] = []
    for taxonomy, tag in candidates:
        fact = facts.get(taxonomy, {}).get(tag)
        if not isinstance(fact, dict):
            continue
        for unit, items in fact.get("units", {}).items():
            for item in items:
                form = safe_str(item.get("form"))
                if form not in ANNUAL_FORMS:
                    continue
                if flow:
                    duration = fact_duration_days(item)
                    if duration is not None and duration < 250:
                        continue
                try:
                    value = float(item["val"])
                except (KeyError, TypeError, ValueError):
                    continue
                values.append(
                    MetricValue(
                        value=value,
                        end=safe_str(item.get("end")),
                        filed=safe_str(item.get("filed")),
                        form=form,
                        fy=safe_str(item.get("fy")),
                        fp=safe_str(item.get("fp")),
                        taxonomy=taxonomy,
                        tag=tag,
                        unit=unit,
                    )
                )
    values.sort(key=lambda row: (row.end, row.filed, row.fy), reverse=True)
    unique: list[MetricValue] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        key = (value.end, value.fy)
        if key in seen:
            continue
        unique.append(value)
        seen.add(key)
    return unique


def latest_metric(facts: dict[str, Any], candidates: list[tuple[str, str]], flow: bool) -> MetricValue | None:
    values = metric_series(facts, candidates, flow)
    return values[0] if values else None


def metric_value(metric: MetricValue | None) -> float | None:
    return metric.value if metric else None


def financial_from_facts(raw: dict[str, str], match: CikMatch, payload: dict[str, Any], retrieved_at: str) -> dict[str, str]:
    financial = base_financial(raw, match, retrieved_at)
    facts = payload.get("facts", {}) if isinstance(payload, dict) else {}
    flow_metrics = {name: latest_metric(facts, tags, flow=True) for name, tags in FLOW_TAGS.items()}
    balance_metrics = {name: latest_metric(facts, tags, flow=False) for name, tags in BALANCE_TAGS.items()}
    revenue_series = metric_series(facts, FLOW_TAGS["revenue"], flow=True)
    net_income_series = metric_series(facts, FLOW_TAGS["net_income"], flow=True)

    revenue = metric_value(flow_metrics["revenue"])
    gross_profit = metric_value(flow_metrics["gross_profit"])
    operating_income = metric_value(flow_metrics["operating_income"])
    net_income = metric_value(flow_metrics["net_income"])
    operating_cash_flow = metric_value(flow_metrics["operating_cash_flow"])
    rd = metric_value(flow_metrics["research_and_development_expense"])
    assets = metric_value(balance_metrics["assets"])
    liabilities = metric_value(balance_metrics["liabilities"])
    equity = metric_value(balance_metrics["stockholders_equity"])
    eps = metric_value(flow_metrics["eps_diluted"])
    shares = metric_value(balance_metrics["shares_outstanding"])
    diluted_shares = metric_value(flow_metrics["weighted_avg_diluted_shares"])

    anchor = flow_metrics["revenue"] or flow_metrics["net_income"] or balance_metrics["assets"]
    source_tags = [metric for metric in [*flow_metrics.values(), *balance_metrics.values()] if metric]
    financial.update(
        {
            "latest_report_context": f"{anchor.form} FY{anchor.fy}" if anchor else "",
            "latest_report_end_date": anchor.end if anchor else "",
            "latest_filed_date": anchor.filed if anchor else "",
            "revenue": fmt_number(revenue),
            "gross_profit": fmt_number(gross_profit),
            "operating_income": fmt_number(operating_income),
            "net_income": fmt_number(net_income),
            "operating_cash_flow": fmt_number(operating_cash_flow),
            "assets": fmt_number(assets),
            "liabilities": fmt_number(liabilities),
            "stockholders_equity": fmt_number(equity),
            "research_and_development_expense": fmt_number(rd),
            "eps_diluted": fmt_number(eps),
            "shares_outstanding": fmt_number(shares),
            "weighted_avg_diluted_shares": fmt_number(diluted_shares),
            "revenue_yoy_pct": pct_change(revenue_series[0].value if len(revenue_series) > 0 else None, revenue_series[1].value if len(revenue_series) > 1 else None),
            "net_income_yoy_pct": pct_change(net_income_series[0].value if len(net_income_series) > 0 else None, net_income_series[1].value if len(net_income_series) > 1 else None),
            "gross_margin_pct": ratio_pct(gross_profit, revenue),
            "operating_margin_pct": ratio_pct(operating_income, revenue),
            "net_margin_pct": ratio_pct(net_income, revenue),
            "roe_pct": ratio_pct(net_income, equity),
            "debt_asset_ratio_pct": ratio_pct(liabilities, assets),
            "operating_cashflow_to_revenue_pct": ratio_pct(operating_cash_flow, revenue),
            "rd_to_revenue_pct": ratio_pct(rd, revenue),
            "fetch_status": "fetched" if source_tags else "not_available",
            "fetch_error": "" if source_tags else "SEC companyfacts returned no selected annual financial metrics",
        }
    )
    return financial


def build_queue_row(
    raw: dict[str, str],
    profile: dict[str, str],
    financial: dict[str, str],
    eligibility: str,
    eligibility_reason: str,
) -> dict[str, str]:
    profile_status = profile.get("fetch_status", "")
    financial_status = financial.get("fetch_status", "")
    errors = [part for part in [profile.get("fetch_error", ""), financial.get("fetch_error", "")] if part]
    if eligibility != "eligible_common_equity":
        research_status = "not_applicable"
        next_action = "exclude_from_company_moat_scoring"
    elif profile_status == "fetched":
        research_status = "evidence_fetched"
        next_action = "score_dimensions"
    else:
        research_status = "pending_evidence"
        next_action = "retry_profile_evidence"
    return {
        "market_type": MARKET_TYPE,
        "market_label": MARKET_LABEL,
        "security_code": raw["security_code"],
        "symbol": raw["symbol"],
        "exchange": raw["exchange"],
        "market": raw["market"],
        "listed_company_name": raw["listed_company_name"],
        "security_name": raw["security_name"],
        "currency": raw["currency"],
        "asset_type_hint": raw.get("asset_type_hint", ""),
        "is_etf": raw.get("is_etf", ""),
        "sec_cik": profile.get("sec_cik", ""),
        "sec_ticker": profile.get("sec_ticker", ""),
        "security_eligibility": eligibility,
        "security_eligibility_reason": eligibility_reason,
        "research_status": research_status,
        "profile_status": profile_status,
        "financial_status": financial_status,
        "retrieved_at_utc": profile.get("retrieved_at_utc") or financial.get("retrieved_at_utc", ""),
        "last_error": " | ".join(errors),
        "next_action": next_action,
    }


def fetch_one(
    raw: dict[str, str],
    cik_map: dict[str, CikMatch],
    timeout: int,
    retries: int,
    user_agent: str,
    min_interval: float,
) -> FetchResult:
    retrieved_at = utc_now()
    eligibility, reason = security_eligibility(raw)
    if eligibility != "eligible_common_equity":
        return not_applicable_rows(raw, eligibility, reason, retrieved_at)

    match = cik_for_row(raw, cik_map)
    if match is None:
        return raw_fallback_rows(raw, eligibility, reason, retrieved_at, "No SEC CIK mapping found for ticker; scored from Nasdaq Trader name only.")

    profile = base_profile(raw, match, retrieved_at)
    financial = base_financial(raw, match, retrieved_at)
    try:
        submission_url = SEC_SUBMISSIONS_URL.format(cik=match.cik)
        submission = request_json(submission_url, timeout, retries, user_agent, min_interval)
        profile = profile_from_submission(raw, match, submission, retrieved_at)
    except Exception as exc:
        profile["fetch_error"] = str(exc)[:500]

    try:
        facts_url = SEC_COMPANYFACTS_URL.format(cik=match.cik)
        payload = request_json(facts_url, timeout, retries, user_agent, min_interval)
        financial = financial_from_facts(raw, match, payload, retrieved_at)
    except Exception as exc:
        financial["fetch_status"] = "not_available"
        financial["fetch_error"] = str(exc)[:500]

    if profile.get("fetch_status") != "fetched":
        fallback = raw_fallback_rows(raw, eligibility, reason, retrieved_at, profile.get("fetch_error", "SEC profile unavailable"))
        profile = fallback.profile | {"sec_cik": str(match.cik), "sec_ticker": match.ticker, "source_url": source_join(sec_source_url(match.cik), raw.get("source_url", ""))}
    return FetchResult(profile=profile, financial=financial, queue=build_queue_row(raw, profile, financial, eligibility, reason))


def run(args: argparse.Namespace) -> tuple[int, int, int, int]:
    _, raw_rows = read_csv(args.raw)
    selected_symbols = {symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()}
    target_rows = raw_rows
    if selected_symbols:
        target_rows = [row for row in raw_rows if row["symbol"].upper() in selected_symbols or row["security_code"].upper() in selected_symbols]
        if not target_rows:
            raise EvidenceFetchError(f"No U.S. raw rows matched --symbols {args.symbols}")
    cik_map = load_cik_map(args.timeout, args.retries, args.user_agent, args.min_request_interval)
    profiles_by_code = {} if args.refresh else read_existing_by_code(args.profiles)
    financials_by_code = {} if args.refresh else read_existing_by_code(args.financials)

    candidates: list[dict[str, str]] = []
    for row in target_rows:
        code = row["security_code"]
        eligibility, _ = security_eligibility(row)
        existing_profile = profiles_by_code.get(code, {})
        existing_financial = financials_by_code.get(code, {})
        stale_not_applicable = eligibility == "eligible_common_equity" and (
            existing_profile.get("fetch_status") == "not_applicable" or existing_financial.get("fetch_status") == "not_applicable"
        )
        profile_done = (
            not stale_not_applicable
            and existing_profile.get("fetch_status") in {"fetched", "not_applicable"}
            and "not attempted" not in existing_profile.get("fetch_error", "").lower()
        )
        financial_done = not stale_not_applicable and existing_financial.get("fetch_status") in {"fetched", "not_available", "not_applicable"}
        if not args.refresh and profile_done and financial_done and not selected_symbols:
            continue
        if args.only_eligible and eligibility != "eligible_common_equity":
            continue
        candidates.append(row)
    if args.limit is not None:
        candidates = candidates[: args.limit]

    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(fetch_one, raw, cik_map, args.timeout, args.retries, args.user_agent, args.min_request_interval): raw
            for raw in candidates
        }
        for future in as_completed(futures):
            raw = futures[future]
            result = future.result()
            profiles_by_code[raw["security_code"]] = result.profile
            financials_by_code[raw["security_code"]] = result.financial
            completed += 1
            if args.progress_every and completed % args.progress_every == 0:
                print(f"Fetched {completed}/{len(candidates)} U.S. evidence rows", file=sys.stderr)

    queue_rows: list[dict[str, str]] = []
    for raw in raw_rows:
        eligibility, reason = security_eligibility(raw)
        code = raw["security_code"]
        if eligibility != "eligible_common_equity":
            result = not_applicable_rows(raw, eligibility, reason, utc_now())
            profiles_by_code[code] = result.profile
            financials_by_code[code] = result.financial
            queue_rows.append(result.queue)
            continue
        if code not in profiles_by_code or code not in financials_by_code:
            result = pending_rows(raw, eligibility, reason, utc_now(), "Evidence fetch not attempted yet.")
            profiles_by_code[code] = result.profile
            financials_by_code[code] = result.financial
        queue_rows.append(build_queue_row(raw, profiles_by_code[code], financials_by_code[code], eligibility, reason))

    write_csv(args.queue, QUEUE_COLUMNS, queue_rows)
    write_csv(args.profiles, PROFILE_COLUMNS, [profiles_by_code[code] for code in sorted(profiles_by_code)])
    write_csv(args.financials, FINANCIAL_COLUMNS, [financials_by_code[code] for code in sorted(financials_by_code)])
    ready_count = sum(1 for row in queue_rows if row["research_status"] == "evidence_fetched")
    not_applicable_count = sum(1 for row in queue_rows if row["research_status"] == "not_applicable")
    return len(candidates), completed, ready_count, not_applicable_count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch U.S. SEC evidence for full-coverage moat scoring.")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--only-eligible", action="store_true")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols/security codes to fetch, leaving existing rows for other securities untouched.")
    parser.add_argument("--progress-every", type=int, default=250)
    parser.add_argument("--min-request-interval", type=float, default=0.11)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    targeted_count, completed_count, ready_count, not_applicable_count = run(args)
    print(f"Targeted {targeted_count} U.S. securities for evidence fetch")
    print(f"Completed {completed_count} fetch attempts")
    print(f"{ready_count} U.S. securities have company evidence for scoring")
    print(f"{not_applicable_count} U.S. securities are not company common-equity instruments")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvidenceFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
