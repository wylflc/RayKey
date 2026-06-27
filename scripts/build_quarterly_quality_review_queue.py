#!/usr/bin/env python3
"""Build the quarterly A-share quality-review queue.

This queue is a deterministic scheduler. It does not decide whether a company
deserves a better or worse tier. It only identifies which companies should be
reviewed under the documented quarterly quality workflow.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "data/raw/a_share_securities.csv"
DEFAULT_ATTENTION_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
DEFAULT_PREVIOUS_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_FINANCIALS = ROOT / "data/interim/a_share_financial_indicators.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_quarterly_quality_review_queue.csv"


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def as_float(value: str | None) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except ValueError:
        return None


def tier_rank(tier: str) -> int:
    if tier.startswith("L1"):
        return 1
    if tier.startswith("L2"):
        return 2
    if tier.startswith("L3"):
        return 3
    if tier.startswith("L4"):
        return 4
    if tier.startswith("L5"):
        return 5
    return 9


def attention_class(row: dict[str, str] | None) -> str:
    if not row:
        return ""
    raw = (
        row.get("attention_class")
        or row.get("initial_attention_class")
        or row.get("watch_class")
        or row.get("watch_action")
        or ""
    ).strip().lower()
    aliases = {
        "值得关注": "worth_attention",
        "watch": "worth_attention",
        "add": "worth_attention",
        "keep": "worth_attention",
        "临界待定": "boundary_pending",
        "boundary": "boundary_pending",
        "pending": "boundary_pending",
        "垃圾公司": "garbage",
        "garbage_company": "garbage",
        "remove": "garbage",
    }
    return aliases.get(raw, raw)


def material_financial_change(financial: dict[str, str] | None) -> list[str]:
    if not financial:
        return []
    reasons: list[str] = []
    revenue_yoy = as_float(financial.get("revenue_yoy_pct"))
    profit_yoy = as_float(financial.get("profit_yoy_pct"))
    gross_margin = as_float(financial.get("gross_margin_pct"))
    net_margin = as_float(financial.get("net_margin_pct"))
    cashflow_to_revenue = as_float(financial.get("cashflow_to_revenue_pct"))
    debt_asset = as_float(financial.get("debt_asset_ratio_pct"))
    research_ratio = as_float(financial.get("research_expense_to_revenue_pct"))

    if revenue_yoy is not None and abs(revenue_yoy) >= 30:
        reasons.append("revenue_yoy_abs_ge_30pct")
    if profit_yoy is not None and abs(profit_yoy) >= 50:
        reasons.append("profit_yoy_abs_ge_50pct")
    if gross_margin is not None and gross_margin >= 45:
        reasons.append("high_gross_margin")
    if net_margin is not None and net_margin >= 20:
        reasons.append("high_net_margin")
    if cashflow_to_revenue is not None and cashflow_to_revenue < -0.05:
        reasons.append("negative_cashflow_to_revenue")
    if debt_asset is not None and debt_asset >= 70:
        reasons.append("high_debt_asset_ratio")
    if research_ratio is not None and research_ratio >= 8:
        reasons.append("high_research_intensity")
    return reasons


def build_queue(
    universe_rows: list[dict[str, str]],
    attention_rows: list[dict[str, str]],
    previous_tier_rows: list[dict[str, str]],
    financial_rows: list[dict[str, str]],
    as_of: str,
) -> list[dict[str, object]]:
    attention_by_code = {row["security_code"].zfill(6): row for row in attention_rows if row.get("security_code")}
    tiers_by_code = {row["security_code"].zfill(6): row for row in previous_tier_rows if row.get("security_code")}
    financials_by_code = {row["security_code"].zfill(6): row for row in financial_rows if row.get("security_code")}

    output: list[dict[str, object]] = []
    as_of_date = parse_date(as_of) or datetime.now(timezone.utc).date()

    for universe_row in universe_rows:
        code = (universe_row.get("security_code") or "").zfill(6)
        if not code:
            continue
        previous = tiers_by_code.get(code)
        financial = financials_by_code.get(code)
        attention = attention_by_code.get(code)
        current_attention_class = attention_class(attention)
        if current_attention_class == "garbage":
            continue

        reasons: list[str] = []

        attention_review_date = parse_date((attention or {}).get("reviewed_at_utc") or (attention or {}).get("triaged_at_utc"))

        if previous is None and current_attention_class not in {"worth_attention", "boundary_pending"}:
            reasons.append("new_or_unreviewed_security")
            current_tier = ""
            current_tier_label = ""
            strategy_tag = ""
            last_quality_review_date = attention_review_date
        else:
            current_tier = (previous or {}).get("quality_tier", "")
            current_tier_label = (previous or {}).get("quality_tier_label", "")
            strategy_tag = (previous or {}).get("primary_strategy_tag", "")
            last_quality_review_date = parse_date((previous or {}).get("reviewed_at_utc")) or attention_review_date
            rank = tier_rank(current_tier)
            if current_attention_class == "worth_attention" and previous is None:
                reasons.append("worth_attention_missing_quality_tier")
            elif rank <= 2:
                reasons.append("l1_l2_routine_quarterly_review")
            elif rank == 3:
                reasons.append("l3_watchlist_recheck")

        latest_report_date = parse_date((financial or {}).get("latest_report_date"))
        if latest_report_date and (last_quality_review_date is None or latest_report_date > last_quality_review_date):
            if current_attention_class == "boundary_pending":
                reasons.append("boundary_pending_latest_report_after_last_review")
            else:
                reasons.append("latest_report_after_last_quality_review")

        financial_change_reasons = material_financial_change(financial)
        if financial_change_reasons:
            if current_attention_class == "boundary_pending":
                reasons.append("boundary_pending_material_financial_change")
            reasons.extend(financial_change_reasons)

        if current_attention_class == "boundary_pending" and not (
            "boundary_pending_latest_report_after_last_review" in reasons
            or "boundary_pending_material_financial_change" in reasons
        ):
            continue

        if not reasons:
            continue

        if (
            "new_or_unreviewed_security" in reasons
            or "latest_report_after_last_quality_review" in reasons
            or "worth_attention_missing_quality_tier" in reasons
        ):
            priority = "high"
        elif "l1_l2_routine_quarterly_review" in reasons:
            priority = "high"
        elif "l3_watchlist_recheck" in reasons or financial_change_reasons or current_attention_class == "boundary_pending":
            priority = "medium"
        else:
            priority = "low"

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "symbol": universe_row.get("symbol", ""),
                "exchange": universe_row.get("exchange", ""),
                "security_name": universe_row.get("security_name", ""),
                "listed_company_name": universe_row.get("listed_company_name", ""),
                "industry": universe_row.get("industry", ""),
                "current_attention_class": current_attention_class,
                "current_quality_tier": current_tier,
                "current_quality_tier_label": current_tier_label,
                "current_strategy_tag": strategy_tag,
                "latest_report_date": latest_report_date.isoformat() if latest_report_date else "",
                "latest_report_type": (financial or {}).get("latest_report_type", ""),
                "last_quality_review_date": last_quality_review_date.isoformat() if last_quality_review_date else "",
                "queue_priority": priority,
                "queue_reasons": ";".join(dict.fromkeys(reasons)),
                "required_authoritative_sources": "latest_annual_report;latest_interim_or_quarterly_report;official_announcement_or_ir;reputable_research_report_when_available",
                "as_of": as_of_date.isoformat(),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    output.sort(key=lambda row: (priority_order.get(str(row["queue_priority"]), 9), row["security_code"]))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="A_SHARE")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--attention-triage", type=Path, default=DEFAULT_ATTENTION_TRIAGE)
    parser.add_argument("--previous-tiers", type=Path, default=DEFAULT_PREVIOUS_TIERS)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.market != "A_SHARE":
        raise SystemExit("Only --market A_SHARE is supported.")
    rows = build_queue(
        load_csv(args.universe),
        load_csv(args.attention_triage),
        load_csv(args.previous_tiers),
        load_csv(args.financials),
        args.as_of,
    )
    fieldnames = [
        "market_type",
        "security_code",
        "symbol",
        "exchange",
        "security_name",
        "listed_company_name",
        "industry",
        "current_attention_class",
        "current_quality_tier",
        "current_quality_tier_label",
        "current_strategy_tag",
        "latest_report_date",
        "latest_report_type",
        "last_quality_review_date",
        "queue_priority",
        "queue_reasons",
        "required_authoritative_sources",
        "as_of",
        "generated_at_utc",
    ]
    write_csv(args.output, rows, fieldnames)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
