#!/usr/bin/env python3
"""Build the A-share core valuation pool.

The pool is the formal input for daily volume-price screening. A security is
eligible only when it is both:

1. an L1/L2 quality company; and
2. not marked as overvalued or impossible to value in the valuation pass.

This script intentionally does not create new valuation opinions. It only
materializes the latest reviewed valuation table into the workflow input.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/a_share_core_valuation_pool.md"

ELIGIBLE_VALUATION_TIERS = {"低估", "较低估", "中性", "可接受较高估"}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def infer_exchange(code: str, tier_row: dict[str, str] | None) -> str:
    if tier_row and tier_row.get("exchange"):
        return tier_row["exchange"]
    if code.startswith(("60", "68", "69")):
        return "SSE"
    if code.startswith(("00", "30")):
        return "SZSE"
    if code.startswith(("43", "83", "87", "92")):
        return "BSE"
    return ""


def normalize_quality_tier(value: str) -> str:
    if value.startswith("L1"):
        return "L1"
    if value.startswith("L2"):
        return "L2"
    return value


def build_pool(
    valuation_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    as_of: str,
) -> list[dict[str, str]]:
    tier_by_code = {row["security_code"].zfill(6): row for row in tier_rows}
    output: list[dict[str, str]] = []

    for row in valuation_rows:
        code = row["security_code"].zfill(6)
        tier_row = tier_by_code.get(code)
        quality_tier = normalize_quality_tier(
            row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", "")
        )
        valuation_tier = row.get("valuation_tier", "")

        if quality_tier not in {"L1", "L2"}:
            continue
        if valuation_tier not in ELIGIBLE_VALUATION_TIERS:
            continue

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "security_name": row.get("security_name", ""),
                "exchange": infer_exchange(code, tier_row),
                "quality_tier": quality_tier,
                "quality_tier_label": row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", ""),
                "strategy_tag": row.get("strategy_tag", ""),
                "valuation_tier": valuation_tier,
                "valuation_batch_id": row.get("valuation_batch_id", ""),
                "valuation_price": row.get("current_price", ""),
                "valuation_pe_ttm": row.get("pe_ttm", ""),
                "valuation_pb": row.get("pb", ""),
                "valuation_reason": row.get("valuation_reason", ""),
                "pool_as_of": as_of,
                "source_file": str(DEFAULT_VALUATION.relative_to(ROOT)),
            }
        )

    return output


def write_markdown(path: Path, rows: list[dict[str, str]], as_of: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# A股核心估值合格池",
        "",
        f"生成日期：{as_of}",
        "",
        "本文件由 `scripts/build_a_share_core_valuation_pool.py` 生成。只包含 L1/L2 且估值档位为低估、较低估、中性或可接受较高估的股票。",
        "",
        "| 代码 | 名称 | 质量 | 估值 | 策略 | 估值价 | PE | PB |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {security_code} | {security_name} | {quality_tier_label} | {valuation_tier} | "
            "{strategy_tag} | {valuation_price} | {valuation_pe_ttm} | {valuation_pb} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).date().isoformat())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_pool(load_csv(args.valuation), load_csv(args.tiers), args.as_of)
    fieldnames = [
        "market_type",
        "security_code",
        "security_name",
        "exchange",
        "quality_tier",
        "quality_tier_label",
        "strategy_tag",
        "valuation_tier",
        "valuation_batch_id",
        "valuation_price",
        "valuation_pe_ttm",
        "valuation_pb",
        "valuation_reason",
        "pool_as_of",
        "source_file",
    ]
    write_csv(args.output_csv, rows, fieldnames)
    write_markdown(args.output_md, rows, args.as_of)
    print(f"wrote {len(rows)} rows to {args.output_csv}")


if __name__ == "__main__":
    main()
