#!/usr/bin/env python3
"""Replay A-share daily signal rules for external validation cases.

This script reuses the same price-signal engine as
`screen_daily_volume_price_signals.py`. It validates whether the volume-price
rules would have fired by a historical date.

Important: quality tier and valuation eligibility are read from the supplied
input file. If the input is the current core valuation pool, those fields are
current metadata, not historical metadata. Historical replay files should
provide an as-of-correct input pool when testing a complete workflow.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from screen_daily_volume_price_signals import scan_one


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/replay_external_validation.csv"


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


def infer_exchange(code: str, row: dict[str, str] | None = None) -> str:
    if row and row.get("exchange"):
        return row["exchange"]
    if code.startswith(("60", "68", "69")):
        return "SSE"
    if code.startswith(("00", "30")):
        return "SZSE"
    if code.startswith(("43", "83", "87", "92")):
        return "BSE"
    return ""


def synthetic_row(code: str, tier_row: dict[str, str] | None) -> dict[str, str]:
    return {
        "market_type": "A_SHARE",
        "security_code": code,
        "security_name": (tier_row or {}).get("security_name", ""),
        "exchange": infer_exchange(code, tier_row),
        "quality_tier": (tier_row or {}).get("quality_tier", ""),
        "quality_tier_label": (tier_row or {}).get("quality_tier_label", ""),
        "strategy_tag": (tier_row or {}).get("primary_strategy_tag", ""),
        "valuation_tier": "",
        "valuation_batch_id": "",
        "valuation_price": "",
        "valuation_pe_ttm": "",
        "valuation_pb": "",
        "valuation_reason": "",
        "pool_as_of": "",
        "source_file": "",
    }


def build_replay_rows(
    input_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    symbols: list[str],
) -> list[tuple[dict[str, str], str, bool]]:
    input_by_code = {row["security_code"].zfill(6): row for row in input_rows}
    tier_by_code = {row["security_code"].zfill(6): row for row in tier_rows}
    result: list[tuple[dict[str, str], str, bool]] = []

    for code in symbols:
        normalized = code.zfill(6)
        if normalized in input_by_code:
            result.append((input_by_code[normalized], "input_pool", True))
        else:
            tier_row = tier_by_code.get(normalized)
            result.append((synthetic_row(normalized, tier_row), "synthetic_not_core_pool", False))
    return result


def parse_symbols(raw: str) -> list[str]:
    symbols = [item.strip().zfill(6) for item in raw.split(",") if item.strip()]
    if not symbols:
        raise SystemExit("--symbols is required and must contain at least one code")
    return symbols


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Replay date in YYYY-MM-DD format. The latest trading day on or before this date is used.")
    parser.add_argument("--symbols", required=True, help="Comma-separated A-share security codes.")
    parser.add_argument("--workflow-version", default="a-share-selection-operation-v1")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="As-of-correct core valuation pool when available.")
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS, help="Fallback current quality-tier file for annotations only.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = parse_symbols(args.symbols)
    input_rows = load_csv(args.input)
    tier_rows = load_csv(args.tiers)
    replay_rows = build_replay_rows(input_rows, tier_rows, symbols)

    output_rows: list[dict[str, object]] = []
    for pool_row, eligibility_source, in_input_pool in replay_rows:
        signal = scan_one(pool_row, args.as_of, args.timeout)
        signal["workflow_version"] = args.workflow_version
        signal["replay_as_of"] = args.as_of
        signal["eligibility_source"] = eligibility_source
        signal["in_input_core_pool"] = in_input_pool
        signal["input_file"] = str(args.input)
        signal["historical_metadata_warning"] = (
            "" if in_input_pool else "Signal replay only; quality/valuation eligibility was not present in the input pool."
        )
        signal["replayed_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        output_rows.append(signal)

    fieldnames = [
        "workflow_version",
        "replay_as_of",
        "trade_date",
        "security_code",
        "security_name",
        "exchange",
        "quality_tier",
        "quality_tier_label",
        "valuation_tier",
        "strategy_tag",
        "in_input_core_pool",
        "eligibility_source",
        "signal_state",
        "priority",
        "action_bias",
        "signals",
        "wait_reasons",
        "close",
        "high",
        "low",
        "pct_chg",
        "amount",
        "ma20",
        "ma60",
        "ret_5d",
        "ret_20d",
        "ret_60d",
        "day_vol_ratio_20",
        "vol_3d_ratio_20",
        "vol_5d_ratio_20",
        "vol_5d_ratio_baseline",
        "vol_percentile_120",
        "close_location",
        "effective_volume",
        "daily_bull",
        "strong_daily_bull",
        "quasi_bull",
        "break_periods",
        "overextended",
        "historical_metadata_warning",
        "input_file",
        "data_source",
        "replayed_at_utc",
    ]
    write_csv(args.output, output_rows, fieldnames)
    print(f"wrote {len(output_rows)} replay rows to {args.output}")


if __name__ == "__main__":
    main()
