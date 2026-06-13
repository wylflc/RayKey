#!/usr/bin/env python3
"""Build the authoritative per-company A-share deep-review queue.

This script does not perform stock analysis. It creates the worklist that must
be completed company by company under the stock-analysis skill: each final
decision requires annual-report evidence, interim/quarterly disclosure or
official announcements, and reputable research evidence where available.
"""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST = ROOT / "data/processed/a_share_final_watchlist.csv"
PRELIMINARY_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
OUTPUT = ROOT / "data/interim/a_share_authoritative_deep_review_queue.csv"
CREATED_AT_UTC = "2026-06-14T00:00:00+00:00"

TIER_PRIORITY = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def numeric(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def sort_key(row: dict[str, str]) -> tuple[int, int, float, str]:
    tier = row.get("_preliminary_quality_tier", "")
    direct = 0 if "direct_watch" in row.get("watch_selection_route", "") else 1
    return (
        TIER_PRIORITY.get(tier, 9),
        direct,
        -numeric(row.get("triage_score", "")),
        row.get("security_code", ""),
    )


def main() -> None:
    watchlist = load_csv(WATCHLIST)
    preliminary_by_code = {
        row["security_code"]: row
        for row in load_csv(PRELIMINARY_TIERS)
    } if PRELIMINARY_TIERS.exists() else {}

    rows: list[dict[str, str]] = []
    for source in watchlist:
        preliminary = preliminary_by_code.get(source["security_code"], {})
        row = dict(source)
        row["_preliminary_quality_tier"] = preliminary.get("quality_tier", "")
        row["_preliminary_quality_tier_label"] = preliminary.get("quality_tier_label", "")
        row["_preliminary_strategy_tag"] = preliminary.get("primary_strategy_tag", "")
        row["_preliminary_peer_rank"] = preliminary.get("peer_rank", "")
        row["_preliminary_peer_count"] = preliminary.get("peer_count", "")
        rows.append(row)

    rows.sort(key=sort_key)

    fields = [
        "market_type",
        "market_label",
        "security_code",
        "security_name",
        "listed_company_name",
        "exchange",
        "industry",
        "peer_groups",
        "review_status",
        "review_batch_id",
        "preliminary_quality_tier",
        "preliminary_quality_tier_label",
        "preliminary_strategy_tag",
        "preliminary_peer_rank",
        "preliminary_peer_count",
        "watch_selection_route",
        "triage_score",
        "triage_decision",
        "required_authoritative_sources",
        "annual_report_source_url",
        "interim_or_quarterly_report_source_url",
        "official_announcement_or_ir_source_url",
        "reputable_research_report_source_url",
        "source_verified_at_utc",
        "primary_strategy_tag_final",
        "secondary_strategy_tags_final",
        "watchlist_decision_final",
        "quality_tier_final",
        "moat_conclusion",
        "capital_replicability_conclusion",
        "technical_or_process_barrier_conclusion",
        "market_space_conclusion",
        "peer_double_check_conclusion",
        "financial_quality_conclusion",
        "valuation_relevance_note",
        "bear_case_summary",
        "base_case_summary",
        "bull_case_summary",
        "invalidation_conditions",
        "monitoring_metrics",
        "analyst_notes",
        "created_at_utc",
    ]

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for index, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "market_type": row["market_type"],
                    "market_label": row["market_label"],
                    "security_code": row["security_code"],
                    "security_name": row["security_name"],
                    "listed_company_name": row["listed_company_name"],
                    "exchange": row["exchange"],
                    "industry": row["industry"],
                    "peer_groups": row["peer_groups"],
                    "review_status": "pending_authoritative_deep_review",
                    "review_batch_id": f"batch-{(index - 1) // 20 + 1:03d}",
                    "preliminary_quality_tier": row["_preliminary_quality_tier"],
                    "preliminary_quality_tier_label": row["_preliminary_quality_tier_label"],
                    "preliminary_strategy_tag": row["_preliminary_strategy_tag"],
                    "preliminary_peer_rank": row["_preliminary_peer_rank"],
                    "preliminary_peer_count": row["_preliminary_peer_count"],
                    "watch_selection_route": row["watch_selection_route"],
                    "triage_score": row["triage_score"],
                    "triage_decision": row["triage_decision"],
                    "required_authoritative_sources": "latest annual report; latest interim or quarterly report; official announcement or IR material; reputable research report when available",
                    "annual_report_source_url": "",
                    "interim_or_quarterly_report_source_url": "",
                    "official_announcement_or_ir_source_url": "",
                    "reputable_research_report_source_url": "",
                    "source_verified_at_utc": "",
                    "primary_strategy_tag_final": "",
                    "secondary_strategy_tags_final": "",
                    "watchlist_decision_final": "",
                    "quality_tier_final": "",
                    "moat_conclusion": "",
                    "capital_replicability_conclusion": "",
                    "technical_or_process_barrier_conclusion": "",
                    "market_space_conclusion": "",
                    "peer_double_check_conclusion": "",
                    "financial_quality_conclusion": "",
                    "valuation_relevance_note": "",
                    "bear_case_summary": "",
                    "base_case_summary": "",
                    "bull_case_summary": "",
                    "invalidation_conditions": "",
                    "monitoring_metrics": "",
                    "analyst_notes": "",
                    "created_at_utc": CREATED_AT_UTC,
                }
            )

    print(OUTPUT.relative_to(ROOT))
    print("rows", len(rows))
    print("batches", (len(rows) + 19) // 20)


if __name__ == "__main__":
    main()
