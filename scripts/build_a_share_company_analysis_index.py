#!/usr/bin/env python3
"""Build the cross-round A-share company analysis index.

One row per A-share security, merging every analysis round this repository has
produced so the history of a company can be read in one place:

1. round1_*: the current ADR-0006 round-1 three-class triage
   (`data/processed/a_share_attention_triage.csv`).
2. prior_*: the closed 2026-06 two-layer review round — peer-group screening
   decision (archived final watchlist), authoritative deep-review quality tier,
   and L1/L2 valuation.
3. decision_log_*: per-security rollup of the workflow decision log.

This script creates no new conclusions and writes nothing to the decision log.
It only materializes existing reviewed results into one reference view.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "data/raw/a_share_securities.csv"
DEFAULT_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
DEFAULT_PRIOR_WATCHLIST = ROOT / "data/archive/2026-06-two-layer-review/a_share_final_watchlist.csv"
DEFAULT_PRIOR_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_PRIOR_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_PRIOR_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_company_analysis_index.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/a_share_company_analysis_index.md"

FIELDNAMES = [
    "security_code",
    "security_name",
    "exchange",
    "board",
    "industry",
    "listing_date",
    "round1_attention_class",
    "round1_attention_reason",
    "round1_note",
    "round1_reviewed_at_utc",
    "prior_final_decision",
    "prior_watch_selection_route",
    "prior_decision_reason",
    "prior_quality_tier",
    "prior_strategy_tag",
    "prior_tier_reason",
    "prior_valuation_tier",
    "prior_valuation_reason",
    "prior_core_pool_eligible",
    "decision_log_entries",
    "decision_log_last_at_utc",
]


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def by_code(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["security_code"].zfill(6): row for row in rows if row.get("security_code")}


def round1_note(row: dict[str, str]) -> str:
    attention_class = row.get("attention_class", "")
    if attention_class == "worth_attention":
        return row.get("capital_replicability_note", "")
    if attention_class == "boundary_pending":
        return row.get("boundary_recheck_trigger", "")
    if attention_class == "garbage":
        subtype = row.get("garbage_subtype", "")
        reason = row.get("garbage_reason", "")
        return f"{subtype}: {reason}" if subtype else reason
    return ""


def build_index(
    universe: list[dict[str, str]],
    triage: list[dict[str, str]],
    prior_watchlist: list[dict[str, str]],
    prior_tiers: list[dict[str, str]],
    prior_valuation: list[dict[str, str]],
    prior_pool: list[dict[str, str]],
    log_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    universe_by_code = by_code(universe)
    triage_by_code = by_code(triage)
    watch_by_code = by_code(prior_watchlist)
    tiers_by_code = by_code(prior_tiers)
    valuation_by_code = by_code(prior_valuation)
    pool_codes = set(by_code(prior_pool))

    log_count: dict[str, int] = {}
    log_last: dict[str, str] = {}
    for row in log_rows:
        code = row.get("security_code", "").strip()
        if not (code.isdigit() and len(code) <= 6):
            continue
        code = code.zfill(6)
        log_count[code] = log_count.get(code, 0) + 1
        logged_at = row.get("logged_at_utc", "")
        if logged_at > log_last.get(code, ""):
            log_last[code] = logged_at

    all_codes = set(universe_by_code) | set(triage_by_code) | set(tiers_by_code) | set(watch_by_code)
    output: list[dict[str, str]] = []
    for code in sorted(all_codes):
        base = universe_by_code.get(code, {})
        tri = triage_by_code.get(code, {})
        watch = watch_by_code.get(code, {})
        tier = tiers_by_code.get(code, {})
        val = valuation_by_code.get(code, {})
        name = (
            base.get("security_name")
            or tri.get("security_name")
            or tier.get("security_name")
            or watch.get("security_name", "")
        )
        output.append(
            {
                "security_code": code,
                "security_name": name,
                "exchange": base.get("exchange") or tier.get("exchange", ""),
                "board": base.get("board", ""),
                "industry": base.get("industry") or tier.get("industry", ""),
                "listing_date": base.get("listing_date", ""),
                "round1_attention_class": tri.get("attention_class", ""),
                "round1_attention_reason": tri.get("attention_reason", ""),
                "round1_note": round1_note(tri),
                "round1_reviewed_at_utc": tri.get("reviewed_at_utc", ""),
                "prior_final_decision": watch.get("final_decision", ""),
                "prior_watch_selection_route": watch.get("watch_selection_route", ""),
                "prior_decision_reason": watch.get("decision_reason", ""),
                "prior_quality_tier": tier.get("quality_tier", ""),
                "prior_strategy_tag": tier.get("primary_strategy_tag", ""),
                "prior_tier_reason": tier.get("tier_qualification_reason", ""),
                "prior_valuation_tier": val.get("valuation_tier", ""),
                "prior_valuation_reason": val.get("valuation_reason", ""),
                "prior_core_pool_eligible": "yes" if code in pool_codes else "",
                "decision_log_entries": str(log_count.get(code, 0)),
                "decision_log_last_at_utc": log_last.get(code, ""),
            }
        )
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> list[str]:
    lines = [
        "| " + " | ".join(header for header, _ in columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        cells = [row.get(field, "").replace("|", "/").replace("\n", " ") for _, field in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def write_markdown(path: Path, rows: list[dict[str, str]], generated_at: str) -> None:
    triaged = [row for row in rows if row["round1_attention_class"]]
    counts: dict[str, int] = {}
    for row in triaged:
        counts[row["round1_attention_class"]] = counts.get(row["round1_attention_class"], 0) + 1
    worth = [row for row in triaged if row["round1_attention_class"] == "worth_attention"]
    worth.sort(key=lambda row: (row["industry"], row["security_code"]))
    garbage = [row for row in triaged if row["round1_attention_class"] == "garbage"]
    garbage.sort(key=lambda row: row["security_code"])

    lines = [
        "# A股公司分析索引（跨轮次）",
        "",
        f"生成时间：{generated_at}",
        "",
        "本文件由 `scripts/build_a_share_company_analysis_index.py` 生成，是既有结论的合并视图，不产生新结论。",
        "每家公司一行，汇总：round1 三类初筛（进行中）、2026-06 两层复核轮（同业校准决策 + 权威深度复核 L1-L5 分层 + L1/L2 估值）、决策日志条数。",
        "完整数据见同名 CSV；逐股完整理由以各轮结果文件为准。",
        "",
        "## 覆盖情况",
        "",
        "| round1 分类 | 家数 |",
        "| --- | ---: |",
        f"| worth_attention | {counts.get('worth_attention', 0)} |",
        f"| boundary_pending | {counts.get('boundary_pending', 0)} |",
        f"| garbage | {counts.get('garbage', 0)} |",
        f"| 尚未重扫 | {len(rows) - len(triaged)} |",
        f"| 合计 | {len(rows)} |",
        "",
        "## round1 值得关注公司（按行业）",
        "",
    ]
    lines += markdown_table(
        worth,
        [
            ("代码", "security_code"),
            ("名称", "security_name"),
            ("行业", "industry"),
            ("上轮档位", "prior_quality_tier"),
            ("上轮策略", "prior_strategy_tag"),
            ("上轮估值", "prior_valuation_tier"),
            ("round1 理由", "round1_attention_reason"),
        ],
    )
    lines += [
        "",
        "## round1 垃圾公司（永久排除）",
        "",
    ]
    lines += markdown_table(
        garbage,
        [
            ("代码", "security_code"),
            ("名称", "security_name"),
            ("行业", "industry"),
            ("排除理由", "round1_note"),
        ],
    )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--prior-watchlist", type=Path, default=DEFAULT_PRIOR_WATCHLIST)
    parser.add_argument("--prior-tiers", type=Path, default=DEFAULT_PRIOR_TIERS)
    parser.add_argument("--prior-valuation", type=Path, default=DEFAULT_PRIOR_VALUATION)
    parser.add_argument("--prior-pool", type=Path, default=DEFAULT_PRIOR_POOL)
    parser.add_argument("--decision-log", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_index(
        load_csv(args.universe),
        load_csv(args.triage),
        load_csv(args.prior_watchlist),
        load_csv(args.prior_tiers),
        load_csv(args.prior_valuation),
        load_csv(args.prior_pool),
        load_csv(args.decision_log),
    )
    write_csv(args.output_csv, rows)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_markdown(args.output_md, rows, generated_at)
    print(f"wrote {len(rows)} rows to {args.output_csv}")


if __name__ == "__main__":
    main()
