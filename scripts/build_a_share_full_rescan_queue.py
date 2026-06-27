#!/usr/bin/env python3
"""Build a full-coverage A-share rescan worklist.

Used when the screening standard changes (e.g. ADR-0005 tier semantics) and the
whole universe must be re-triaged and re-tiered. This is a deterministic
scheduler: it queues every eligible security with its prior attention class and
tier for reference, but it does not decide any new attention class or tier.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "data/raw/a_share_securities.csv"
DEFAULT_PRIOR_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_full_rescan_queue.csv"

FIELDNAMES = [
    "security_code", "symbol", "exchange", "board", "security_name",
    "listed_company_name", "industry", "listing_date",
    "prior_attention_class", "prior_quality_tier", "prior_strategy_tag",
    "rescan_status", "rescan_priority", "required_authoritative_sources",
    "as_of", "generated_at_utc",
]


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def build(universe: list[dict[str, str]], prior: list[dict[str, str]], as_of: str) -> list[dict[str, object]]:
    prior_by_code = {row["security_code"].zfill(6): row for row in prior if row.get("security_code")}
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, object]] = []
    for sec in universe:
        code = (sec.get("security_code") or "").zfill(6)
        if not code:
            continue
        p = prior_by_code.get(code)
        attention = (p or {}).get("current_attention_class", "")
        tier = (p or {}).get("quality_tier", "")
        if attention == "worth_attention":
            priority = "1_worth_attention"
        elif attention == "boundary_pending":
            priority = "2_ex_l5_boundary"
        else:
            priority = "3_unreviewed"
        rows.append(
            {
                "security_code": code,
                "symbol": sec.get("symbol", ""),
                "exchange": sec.get("exchange", ""),
                "board": sec.get("board", ""),
                "security_name": sec.get("security_name", ""),
                "listed_company_name": sec.get("listed_company_name", ""),
                "industry": sec.get("industry", ""),
                "listing_date": sec.get("listing_date", ""),
                "prior_attention_class": attention,
                "prior_quality_tier": tier,
                "prior_strategy_tag": (p or {}).get("primary_strategy_tag", ""),
                "rescan_status": "pending_rescan",
                "rescan_priority": priority,
                "required_authoritative_sources": "latest_annual_report;latest_interim_or_quarterly_report;official_announcement_or_ir;reputable_research_report_when_available",
                "as_of": as_of,
                "generated_at_utc": generated,
            }
        )
    rows.sort(key=lambda r: (r["rescan_priority"], r["security_code"]))
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--prior-tiers", type=Path, default=DEFAULT_PRIOR_TIERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build(load_csv(args.universe), load_csv(args.prior_tiers), args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    from collections import Counter
    by_priority = Counter(r["rescan_priority"] for r in rows)
    print(f"wrote {len(rows)} rows to {args.output}")
    for key in sorted(by_priority):
        print(f"  {key}: {by_priority[key]}")


if __name__ == "__main__":
    main()
