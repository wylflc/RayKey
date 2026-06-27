#!/usr/bin/env python3
"""Build the report-driven quality and valuation update queue."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTENTION_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_FINANCIALS = ROOT / "data/interim/a_share_financial_indicators.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_report_update_queue.csv"


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


def is_core_tier(tier: str) -> bool:
    return tier.startswith("L1") or tier.startswith("L2")


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


def build_queue(
    attention_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    valuation_rows: list[dict[str, str]],
    financial_rows: list[dict[str, str]],
    as_of: str,
) -> list[dict[str, object]]:
    attention_by_code = {row["security_code"].zfill(6): row for row in attention_rows if row.get("security_code")}
    financials_by_code = {row["security_code"].zfill(6): row for row in financial_rows if row.get("security_code")}
    valuation_by_code = {row["security_code"].zfill(6): row for row in valuation_rows if row.get("security_code")}
    as_of_date = parse_date(as_of) or datetime.now(timezone.utc).date()
    output: list[dict[str, object]] = []

    for tier in tier_rows:
        code = tier.get("security_code", "").zfill(6)
        if not code:
            continue
        current_attention_class = attention_class(attention_by_code.get(code))
        if current_attention_class == "garbage":
            continue
        financial = financials_by_code.get(code)
        valuation = valuation_by_code.get(code)
        latest_report_date = parse_date((financial or {}).get("latest_report_date"))
        last_quality_review_date = parse_date(tier.get("reviewed_at_utc"))
        last_valuation_review_date = parse_date((valuation or {}).get("pool_as_of"))
        quality_review_needed = bool(
            latest_report_date and (last_quality_review_date is None or latest_report_date > last_quality_review_date)
        )
        valuation_review_needed = bool(
            is_core_tier(tier.get("quality_tier", ""))
            and latest_report_date
            and (last_valuation_review_date is None or latest_report_date > last_valuation_review_date)
        )

        event_reasons: list[str] = []
        if quality_review_needed:
            event_reasons.append("latest_report_after_last_quality_review")
        if valuation_review_needed:
            event_reasons.append("latest_report_after_last_valuation_review")

        if not event_reasons:
            continue

        if valuation_review_needed:
            update_scope = "quality_and_valuation"
            priority = "high"
        elif quality_review_needed:
            update_scope = "quality_only"
            priority = "medium"
        else:
            update_scope = "none"
            priority = "low"

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "security_name": tier.get("security_name", ""),
                "listed_company_name": tier.get("listed_company_name", ""),
                "exchange": tier.get("exchange", ""),
                "attention_class": current_attention_class,
                "quality_tier": tier.get("quality_tier", ""),
                "quality_tier_label": tier.get("quality_tier_label", ""),
                "strategy_tag": tier.get("primary_strategy_tag", ""),
                "latest_report_date": latest_report_date.isoformat() if latest_report_date else "",
                "latest_report_type": (financial or {}).get("latest_report_type", ""),
                "last_quality_review_date": last_quality_review_date.isoformat() if last_quality_review_date else "",
                "last_valuation_review_date": last_valuation_review_date.isoformat() if last_valuation_review_date else "",
                "quality_review_needed": quality_review_needed,
                "valuation_review_needed": valuation_review_needed,
                "update_scope": update_scope,
                "queue_priority": priority,
                "queue_reasons": ";".join(event_reasons),
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
    parser.add_argument("--attention-triage", type=Path, default=DEFAULT_ATTENTION_TRIAGE)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--valuation-pool", type=Path, default=DEFAULT_VALUATION_POOL)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.market != "A_SHARE":
        raise SystemExit("Only --market A_SHARE is supported.")
    rows = build_queue(
        load_csv(args.attention_triage),
        load_csv(args.tiers),
        load_csv(args.valuation_pool),
        load_csv(args.financials),
        args.as_of,
    )
    fieldnames = [
        "market_type",
        "security_code",
        "security_name",
        "listed_company_name",
        "exchange",
        "attention_class",
        "quality_tier",
        "quality_tier_label",
        "strategy_tag",
        "latest_report_date",
        "latest_report_type",
        "last_quality_review_date",
        "last_valuation_review_date",
        "quality_review_needed",
        "valuation_review_needed",
        "update_scope",
        "queue_priority",
        "queue_reasons",
        "as_of",
        "generated_at_utc",
    ]
    write_csv(args.output, rows, fieldnames)
    print(f"wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
