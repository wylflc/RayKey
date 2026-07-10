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

from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/a_share_core_valuation_pool.md"

# §6.2.1 分层×估值准入矩阵：层级越低，买入估值门槛越严。
TIER_ELIGIBLE_VALUATIONS = {
    "L1": {"低估", "较低估", "中性", "可接受较高估"},
    "L2": {"低估", "较低估", "中性"},
    "L3": {"低估", "较低估"},
    "L4": {"低估"},
}
CORE_LAYER_TIERS = {"L1", "L2"}
# v20 §6.7.5：未过准入矩阵但估值非高估/非无法估值的 L1-L4 → watch_only 仅观察层。
WATCH_VALUATIONS = {"低估", "较低估", "中性", "可接受较高估"}


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
    for tier in ("L1", "L2", "L3", "L4", "L5"):
        if value.startswith(tier):
            return tier
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

        eligible = TIER_ELIGIBLE_VALUATIONS.get(quality_tier)
        if eligible is None:
            continue
        if valuation_tier in eligible:
            pool_layer = "core" if quality_tier in CORE_LAYER_TIERS else "tactical"
        elif valuation_tier in WATCH_VALUATIONS:
            pool_layer = "watch_only"
        else:
            continue

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "security_name": row.get("security_name", ""),
                "exchange": infer_exchange(code, tier_row),
                "quality_tier": quality_tier,
                "quality_tier_label": row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", ""),
                "pool_layer": pool_layer,
                "strategy_tag": row.get("strategy_tag", ""),
                "valuation_tier": valuation_tier,
                "valuation_batch_id": row.get("valuation_batch_id", ""),
                "valuation_price": row.get("current_price", ""),
                "valuation_pe_ttm": row.get("pe_ttm", ""),
                "valuation_pb": row.get("pb", ""),
                "valuation_reason": row.get("valuation_reason", ""),
                # §6.7：估值结论日原样透传；pool_as_of 只是物化日，不得当估值复核日用。
                "valuation_reviewed_at": row.get("valuation_reviewed_at", ""),
                "valuation_price_as_of": row.get("valuation_price_as_of", ""),
                "evidence_available_at": row.get("evidence_available_at", ""),
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
        "本文件由 `scripts/build_a_share_core_valuation_pool.py` 生成。core/tactical 为按 §6.2.1 矩阵可买层；watch_only 为仅观察层（v20，可见不可买）。",
        "",
        "| 代码 | 名称 | 质量 | 层 | 估值 | 策略 | 估值价 | PE | PB |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {security_code} | {security_name} | {quality_tier_label} | {pool_layer} | {valuation_tier} | "
            "{strategy_tag} | {valuation_price} | {valuation_pe_ttm} | {valuation_pb} |".format(**row)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def log_pool_decisions(
    log_file: Path,
    rows: list[dict[str, str]],
    as_of: str,
    valuation_file: Path,
    tiers_file: Path,
    output_csv: Path,
    output_md: Path,
) -> None:
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    append_decision_log(
        log_file,
        [
            {
                "logged_at_utc": logged_at,
                "workflow_stage": "core_valuation_pool",
                "run_id": f"core_valuation_pool:{as_of}",
                "as_of": as_of,
                "security_code": row["security_code"],
                "security_name": row["security_name"],
                "decision_type": "scan_watch_only" if row["pool_layer"] == "watch_only" else "core_valuation_eligible",
                "decision_result": (
                    f"watch_only({row['valuation_tier']})" if row["pool_layer"] == "watch_only" else row["valuation_tier"]
                ),
                "summary_reason": row.get("valuation_reason", ""),
                "input_files": f"{valuation_file};{tiers_file}",
                "source_urls": "",
                "output_file": f"{output_csv};{output_md}",
                "operator_or_script": "scripts/build_a_share_core_valuation_pool.py",
                "workflow_version": WORKFLOW_VERSION,
            }
            for row in rows
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--valuation", type=Path, default=DEFAULT_VALUATION)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
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
        "pool_layer",
        "strategy_tag",
        "valuation_tier",
        "valuation_batch_id",
        "valuation_price",
        "valuation_pe_ttm",
        "valuation_pb",
        "valuation_reason",
        "valuation_reviewed_at",
        "valuation_price_as_of",
        "evidence_available_at",
        "pool_as_of",
        "source_file",
    ]
    write_csv(args.output_csv, rows, fieldnames)
    write_markdown(args.output_md, rows, args.as_of)
    log_pool_decisions(
        args.log_file,
        rows,
        args.as_of,
        args.valuation,
        args.tiers,
        args.output_csv,
        args.output_md,
    )
    print(f"wrote {len(rows)} rows to {args.output_csv}")


if __name__ == "__main__":
    main()
