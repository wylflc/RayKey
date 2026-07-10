#!/usr/bin/env python3
"""Fetch per-security valuation evidence for the §6 L1-L4 valuation pass.

For each requested security the script retrieves, from Eastmoney public
endpoints: real-time quote (price / market cap / PE-TTM / PB), up to 40
periods of main financial indicators (quarterly cumulative), daily valuation
history (PE-TTM / PB percentile bands), latest earnings pre-announcements
(业绩预告) and express reports (业绩快报), and the F10 analyst profit
forecast. Raw per-security evidence is written to
`data/interim/valuation_evidence/{code}.json`; a derived one-row-per-security
summary is upserted into `data/interim/a_share_valuation_evidence_summary.csv`.

The script only gathers evidence. Valuation tier judgment stays with the
model per docs/000_Ashare_workflow.md §6.5/§6.6.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"
DEFAULT_SUMMARY = ROOT / "data/interim/a_share_valuation_evidence_summary.csv"

QUOTE_ENDPOINT = "https://push2.eastmoney.com/api/qt/ulist.np/get"
DATACENTER_ENDPOINT = "https://datacenter-web.eastmoney.com/api/data/v1/get"
F10_FORECAST_ENDPOINT = "https://emweb.securities.eastmoney.com/PC_HSF10/ProfitForecast/PageAjax"
F10_FINANCE_ENDPOINT = "https://datacenter.eastmoney.com/securities/api/data/get"

FINANCE_PERIOD_KEYS = [
    "REPORT_DATE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "TOTALOPERATEREVE",
    "TOTALOPERATEREVETZ",
    "PARENTNETPROFIT",
    "PARENTNETPROFITTZ",
    "KCFJCXSYJLR",
    "KCFJCXSYJLRTZ",
    "EPSJB",
    "XSMLL",
    "XSJLL",
    "ROEJQ",
    "ROIC",
    "MGJYXJJE",
    "JYXJLYYSR",
    "ZCFZL",
]

PREDICT_KEYS = [
    "REPORT_DATE",
    "NOTICE_DATE",
    "PREDICT_FINANCE_CODE",
    "PREDICT_TYPE",
    "PREDICT_AMT_LOWER",
    "PREDICT_AMT_UPPER",
    "ADD_AMP_LOWER",
    "ADD_AMP_UPPER",
    "PREDICT_CONTENT",
    "CHANGE_REASON_EXPLAIN",
]

EXPRESS_KEYS = [
    "REPORT_DATE",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "TOTAL_OPERATE_INCOME",
    "YSTZ",
    "PARENT_NETPROFIT",
    "JLRTBZCL",
    "WEIGHTAVG_ROE",
    "BASIC_EPS",
]

SUMMARY_COLUMNS = [
    "security_code",
    "security_name",
    "quote_price",
    "quote_change_pct",
    "total_market_cap",
    "float_market_cap",
    "pe_ttm_provider",
    "pe_dynamic_provider",
    "pb_provider",
    "ttm_parent_profit",
    "ttm_deducted_profit",
    "pe_ttm_computed",
    "pe_ttm_deducted_computed",
    "fy_latest_report_date",
    "fy_parent_profit",
    "fy_profit_yoy_pct",
    "latest_quarter_report_date",
    "latest_quarter_notice_date",
    "latest_quarter_revenue_yoy_pct",
    "latest_quarter_profit_yoy_pct",
    "latest_quarter_deducted_yoy_pct",
    "pe_ttm_pct_rank_5y",
    "pb_pct_rank_5y",
    "pe_ttm_5y_median",
    "pb_5y_median",
    "latest_predict_report_date",
    "latest_predict_notice_date",
    "latest_predict_type",
    "latest_predict_summary",
    "latest_express_report_date",
    "latest_express_summary",
    "forecast_years",
    "forecast_profit_means",
    "evidence_available_at",
    "retrieved_at_utc",
    "fetch_status",
    "fetch_error",
]


class FetchError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def secid(code: str) -> str:
    if code.startswith(("60", "68", "69", "51", "56", "58")):
        return f"1.{code}"
    if code.startswith(("00", "30", "12", "15", "18")):
        return f"0.{code}"
    if code.startswith(("43", "83", "87", "92")):
        return f"0.{code}"
    raise FetchError(f"cannot infer exchange for {code}")


def em_secucode(code: str) -> str:
    """Eastmoney SECUCODE filter format, e.g. 600519.SH."""
    return f"{code}.{'SH' if secid(code).startswith('1.') else 'SZ'}"


def em_pageajax_code(code: str) -> str:
    """PC_HSF10 PageAjax code format, e.g. SH600519."""
    return f"{'SH' if secid(code).startswith('1.') else 'SZ'}{code}"


def request_json(url: str, timeout: int = 20, retries: int = 2) -> Any:
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
                text = body.decode("utf-8")
                if text.startswith(("jQuery", "callback", "(")):
                    text = text[text.index("(") + 1 : text.rindex(")")]
                return json.loads(text)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.6 * (attempt + 1))
    raise FetchError(str(last_error))


def safe_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return ""
    return f"{number:.6f}".rstrip("0").rstrip(".")


def fetch_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    secids = ",".join(secid(code) for code in codes)
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f2,f3,f9,f12,f14,f20,f21,f23,f115,f124",
        "secids": secids,
    }
    url = f"{QUOTE_ENDPOINT}?{urllib.parse.urlencode(params)}"
    payload = request_json(url)
    rows = (payload.get("data") or {}).get("diff") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("f12", ""))
        result[code] = {
            "price": row.get("f2"),
            "change_pct": row.get("f3"),
            "pe_dynamic": row.get("f9"),
            "pe_ttm": row.get("f115"),
            "pb": row.get("f23"),
            "total_market_cap": row.get("f20"),
            "float_market_cap": row.get("f21"),
            "quote_time": row.get("f124"),
            "name": row.get("f14"),
            "source_url": url,
        }
    return result


def fetch_finance_periods(code: str, periods: int = 40) -> tuple[list[dict[str, Any]], str]:
    params = {
        "filter": f'(SECUCODE="{em_secucode(code)}")',
        "client": "APP",
        "source": "HSF10",
        "type": "RPT_F10_FINANCE_MAINFINADATA",
        "sty": "APP_F10_MAINFINADATA",
        "st": "REPORT_DATE",
        "ps": str(periods),
        "sr": "-1",
    }
    url = f"{F10_FINANCE_ENDPOINT}?{urllib.parse.urlencode(params)}"
    payload = request_json(url)
    rows = ((payload.get("result") or {}).get("data")) or []
    trimmed = [{key: row.get(key) for key in FINANCE_PERIOD_KEYS} for row in rows]
    return trimmed, url


def fetch_datacenter(report_name: str, code: str, sort_col: str, page_size: int) -> tuple[list[dict[str, Any]], str]:
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortTypes": "-1",
        "sortColumns": sort_col,
        "source": "WEB",
        "client": "WEB",
    }
    url = f"{DATACENTER_ENDPOINT}?{urllib.parse.urlencode(params)}"
    payload = request_json(url)
    rows = ((payload.get("result") or {}).get("data")) or []
    return rows, url


def fetch_forecast(code: str) -> tuple[dict[str, Any], str]:
    url = f"{F10_FORECAST_ENDPOINT}?code={em_pageajax_code(code)}"
    payload = request_json(url)
    trimmed: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list):
                trimmed[key] = value[:16]
            else:
                trimmed[key] = value
    return trimmed, url


def percentile_rank(series: list[float], value: float) -> float:
    below = sum(1 for item in series if item <= value)
    return below / len(series) * 100


def build_valuation_band(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pe_series = [safe_float(row.get("PE_TTM")) for row in rows]
    pb_series = [safe_float(row.get("PB_MRQ")) for row in rows]
    pe_series = [item for item in pe_series if item is not None and item > 0]
    pb_series = [item for item in pb_series if item is not None and item > 0]
    band: dict[str, Any] = {}
    if rows:
        band["window_start"] = rows[-1].get("TRADE_DATE", "")
        band["window_end"] = rows[0].get("TRADE_DATE", "")
        current = rows[0]
        band["current_pe_ttm"] = current.get("PE_TTM")
        band["current_pb"] = current.get("PB_MRQ")
        band["current_ps_ttm"] = current.get("PS_TTM")
        band["current_pcf"] = current.get("PCF_OCF_TTM")
    if pe_series:
        current_pe = pe_series[0]
        band["pe_ttm_pct_rank"] = round(percentile_rank(pe_series, current_pe), 1)
        band["pe_ttm_min"] = min(pe_series)
        band["pe_ttm_median"] = round(statistics.median(pe_series), 2)
        band["pe_ttm_max"] = max(pe_series)
    if pb_series:
        current_pb = pb_series[0]
        band["pb_pct_rank"] = round(percentile_rank(pb_series, current_pb), 1)
        band["pb_min"] = min(pb_series)
        band["pb_median"] = round(statistics.median(pb_series), 2)
        band["pb_max"] = max(pb_series)
    return band


def ttm_from_periods(periods: list[dict[str, Any]], key: str) -> float | None:
    """TTM = latest annual + latest cumulative quarter - same quarter last year.

    Periods are cumulative and sorted latest-first. When the latest period is
    an annual report the TTM equals that annual value.
    """
    if not periods:
        return None
    latest = periods[0]
    latest_date = str(latest.get("REPORT_DATE") or "")[:10]
    latest_value = safe_float(latest.get(key))
    if latest_value is None:
        return None
    if latest_date.endswith("-12-31"):
        return latest_value
    annual = next(
        (row for row in periods if str(row.get("REPORT_DATE") or "").endswith("12-31 00:00:00") or str(row.get("REPORT_DATE") or "")[:10].endswith("-12-31")),
        None,
    )
    if annual is None:
        return None
    annual_value = safe_float(annual.get(key))
    prior_date = latest_date.replace(latest_date[:4], str(int(latest_date[:4]) - 1), 1)
    prior = next((row for row in periods if str(row.get("REPORT_DATE") or "")[:10] == prior_date), None)
    prior_value = safe_float(prior.get(key)) if prior else None
    if annual_value is None or prior_value is None:
        return None
    return annual_value + latest_value - prior_value


def summarize(code: str, evidence: dict[str, Any]) -> dict[str, str]:
    quote = evidence.get("quote") or {}
    periods = evidence.get("finance_periods") or []
    band = evidence.get("valuation_band") or {}
    predicts = evidence.get("performance_predicts") or []
    expresses = evidence.get("performance_express") or []
    forecast = evidence.get("profit_forecast") or {}

    latest = periods[0] if periods else {}
    annual = next((row for row in periods if str(row.get("REPORT_DATE") or "")[:10].endswith("-12-31")), {})

    ttm_profit = ttm_from_periods(periods, "PARENTNETPROFIT")
    ttm_deducted = ttm_from_periods(periods, "KCFJCXSYJLR")
    total_mv = safe_float(quote.get("total_market_cap"))
    pe_computed = total_mv / ttm_profit if total_mv and ttm_profit and ttm_profit > 0 else None
    pe_deducted = total_mv / ttm_deducted if total_mv and ttm_deducted and ttm_deducted > 0 else None

    predict = predicts[0] if predicts else {}
    express = expresses[0] if expresses else {}
    predict_summary = ""
    if predict:
        low, high = predict.get("PREDICT_AMT_LOWER"), predict.get("PREDICT_AMT_UPPER")
        amp_low, amp_high = predict.get("ADD_AMP_LOWER"), predict.get("ADD_AMP_UPPER")
        predict_summary = (
            f"{predict.get('PREDICT_TYPE', '')} {predict.get('PREDICT_FINANCE_CODE', '')}"
            f" 金额[{fmt(low)},{fmt(high)}] 幅度[{fmt(amp_low)},{fmt(amp_high)}]%"
        ).strip()
    express_summary = ""
    if express:
        express_summary = (
            f"营收{fmt(express.get('TOTAL_OPERATE_INCOME'))}(同比{fmt(express.get('YSTZ'))}%)"
            f" 净利{fmt(express.get('PARENT_NETPROFIT'))}(同比{fmt(express.get('JLRTBZCL'))}%)"
        )

    forecast_years: list[str] = []
    forecast_means: list[str] = []
    for row in forecast.get("yctj_list", []) or []:
        year = str(row.get("YEAR", ""))
        mark = str(row.get("YEAR_MARK", ""))
        profit = row.get("PARENT_NETPROFIT")
        if year and mark:
            forecast_years.append(f"{year}{mark}")
            forecast_means.append(fmt(profit))

    notice_dates = [str(latest.get("NOTICE_DATE") or "")[:10], str(predict.get("NOTICE_DATE") or "")[:10], str(express.get("NOTICE_DATE") or "")[:10]]
    evidence_available_at = max((item for item in notice_dates if item), default="")

    return {
        "security_code": code,
        "security_name": str(quote.get("name") or ""),
        "quote_price": fmt(quote.get("price")),
        "quote_change_pct": fmt(quote.get("change_pct")),
        "total_market_cap": fmt(quote.get("total_market_cap")),
        "float_market_cap": fmt(quote.get("float_market_cap")),
        "pe_ttm_provider": fmt(quote.get("pe_ttm")),
        "pe_dynamic_provider": fmt(quote.get("pe_dynamic")),
        "pb_provider": fmt(quote.get("pb")),
        "ttm_parent_profit": fmt(ttm_profit),
        "ttm_deducted_profit": fmt(ttm_deducted),
        "pe_ttm_computed": fmt(pe_computed),
        "pe_ttm_deducted_computed": fmt(pe_deducted),
        "fy_latest_report_date": str(annual.get("REPORT_DATE") or "")[:10],
        "fy_parent_profit": fmt(annual.get("PARENTNETPROFIT")),
        "fy_profit_yoy_pct": fmt(annual.get("PARENTNETPROFITTZ")),
        "latest_quarter_report_date": str(latest.get("REPORT_DATE") or "")[:10],
        "latest_quarter_notice_date": str(latest.get("NOTICE_DATE") or "")[:10],
        "latest_quarter_revenue_yoy_pct": fmt(latest.get("TOTALOPERATEREVETZ")),
        "latest_quarter_profit_yoy_pct": fmt(latest.get("PARENTNETPROFITTZ")),
        "latest_quarter_deducted_yoy_pct": fmt(latest.get("KCFJCXSYJLRTZ")),
        "pe_ttm_pct_rank_5y": fmt(band.get("pe_ttm_pct_rank")),
        "pb_pct_rank_5y": fmt(band.get("pb_pct_rank")),
        "pe_ttm_5y_median": fmt(band.get("pe_ttm_median")),
        "pb_5y_median": fmt(band.get("pb_median")),
        "latest_predict_report_date": str(predict.get("REPORT_DATE") or "")[:10],
        "latest_predict_notice_date": str(predict.get("NOTICE_DATE") or "")[:10],
        "latest_predict_type": str(predict.get("PREDICT_TYPE") or ""),
        "latest_predict_summary": predict_summary,
        "latest_express_report_date": str(express.get("REPORT_DATE") or "")[:10],
        "latest_express_summary": express_summary,
        "forecast_years": ";".join(forecast_years),
        "forecast_profit_means": ";".join(forecast_means),
        "evidence_available_at": evidence_available_at,
        "retrieved_at_utc": evidence.get("retrieved_at_utc", ""),
        "fetch_status": evidence.get("fetch_status", ""),
        "fetch_error": evidence.get("fetch_error", ""),
    }


def fetch_one(code: str, quote: dict[str, Any]) -> dict[str, Any]:
    retrieved_at = utc_now()
    evidence: dict[str, Any] = {
        "security_code": code,
        "retrieved_at_utc": retrieved_at,
        "quote": quote,
        "source_urls": {},
        "fetch_status": "fetched",
        "fetch_error": "",
    }
    errors: list[str] = []
    try:
        periods, url = fetch_finance_periods(code)
        evidence["finance_periods"] = periods
        evidence["source_urls"]["finance"] = url
    except Exception as exc:
        errors.append(f"finance:{exc}")
        evidence["finance_periods"] = []
    try:
        rows, url = fetch_datacenter("RPT_VALUEANALYSIS_DET", code, "TRADE_DATE", 1250)
        evidence["valuation_band"] = build_valuation_band(rows)
        evidence["source_urls"]["valuation_history"] = url
    except Exception as exc:
        errors.append(f"valuation_history:{exc}")
        evidence["valuation_band"] = {}
    try:
        rows, url = fetch_datacenter("RPT_PUBLIC_OP_NEWPREDICT", code, "NOTICE_DATE", 6)
        evidence["performance_predicts"] = [{key: row.get(key) for key in PREDICT_KEYS} for row in rows]
        evidence["source_urls"]["performance_predict"] = url
    except Exception as exc:
        errors.append(f"predict:{exc}")
        evidence["performance_predicts"] = []
    try:
        rows, url = fetch_datacenter("RPT_FCI_PERFORMANCEE", code, "REPORT_DATE", 4)
        evidence["performance_express"] = [{key: row.get(key) for key in EXPRESS_KEYS} for row in rows]
        evidence["source_urls"]["performance_express"] = url
    except Exception as exc:
        errors.append(f"express:{exc}")
        evidence["performance_express"] = []
    try:
        forecast, url = fetch_forecast(code)
        evidence["profit_forecast"] = forecast
        evidence["source_urls"]["profit_forecast"] = url
    except Exception as exc:
        errors.append(f"forecast:{exc}")
        evidence["profit_forecast"] = {}
    if errors:
        evidence["fetch_status"] = "partial" if evidence.get("finance_periods") else "error"
        evidence["fetch_error"] = " | ".join(errors)[:500]
    return evidence


def upsert_summary(path: Path, rows: list[dict[str, str]]) -> None:
    existing: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                existing[row["security_code"]] = row
    for row in rows:
        existing[row["security_code"]] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for code in sorted(existing):
            writer.writerow({key: existing[code].get(key, "") for key in SUMMARY_COLUMNS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch A-share valuation evidence for §6 review.")
    parser.add_argument("--codes", required=True, help="comma separated 6-digit security codes")
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)

    codes = [code.strip().zfill(6) for code in args.codes.split(",") if code.strip()]
    quotes = fetch_quotes(codes)

    summaries: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(fetch_one, code, quotes.get(code, {})): code for code in codes}
        for future in as_completed(futures):
            code = futures[future]
            evidence = future.result()
            args.evidence_dir.mkdir(parents=True, exist_ok=True)
            out_path = args.evidence_dir / f"{code}.json"
            out_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=1), encoding="utf-8")
            summary = summarize(code, evidence)
            summaries.append(summary)
            print(f"{code} {summary['security_name']}: {summary['fetch_status']} price={summary['quote_price']} peTTM={summary['pe_ttm_provider']}", file=sys.stderr)

    upsert_summary(args.summary, summaries)
    print(f"Fetched {len(summaries)} securities; summary -> {args.summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
