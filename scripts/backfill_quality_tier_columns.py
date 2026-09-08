#!/usr/bin/env python3
"""补建质量分层研究字段，保留已有值，并打印填充率。

只从已有文字转录侵蚀路径，不自动打分或改变名单、档位。
L3 战术理由由研究者逐票填写，供工作流程的买入闸门读取。
用 --check 只检查不写回。
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"

# 质量分层表里这六个研究字段此前从未建列（OI-024）。
MISSING_COLUMNS = [
    "q1_reason",
    "q2_moat_type",
    "q2_erosion_paths",
    "q3_reason",
    "q4_reason",
    "tactical_thesis",
]

# 实测三种写法并存：`前瞻侵蚀：`／`前瞻侵蚀（规则8显式标注）：`／`前瞻侵蚀（规则8标注）：`。
# 只认死第一种会漏 10 行，而漏掉的恰好是 AI/半导体那一批（含一家 L1 澜起科技）——
# 正是 §13 第 3 条点名的「某列本该命中却没写」。
EROSION_MARKER = re.compile(r"前瞻侵蚀[^：:]*[：:]")
EROSION_FLAG = re.compile(r"erosion_path\(([^)]*)\)")


def ensure_columns(rows: list[dict[str, str]], fields: list[str]) -> list[str]:
    for column in MISSING_COLUMNS:
        if column not in fields:
            fields.append(column)
    for row in rows:
        for column in MISSING_COLUMNS:
            row.setdefault(column, "")
    return fields


def transcribe_erosion_paths(rows: list[dict[str, str]]) -> int:
    """把 `moat_summary` 的「前瞻侵蚀：」段转录进 `q2_erosion_paths`。

    只转录、不改写：原句一字不动地搬过去，命中 `erosion_path` 旗标的再把旗标里的
    「路径,概率」标注并到句首——**概率判定本身来自旗标，不是本脚本产生的新判断**。
    """
    filled = 0
    for row in rows:
        if (row.get("q2_erosion_paths") or "").strip():
            continue
        summary = row.get("moat_summary") or ""
        match = EROSION_MARKER.search(summary)
        if not match:
            continue
        text = summary[match.end():].strip()
        flag = EROSION_FLAG.search(row.get("flags") or "")
        if flag:
            text = f"[旗标 {flag.group(1)}] {text}"
        row["q2_erosion_paths"] = text
        filled += 1
    return filled


def report_fill_rates(rows: list[dict[str, str]]) -> None:
    total = len(rows)
    by_tier: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_tier.setdefault(row.get("quality_tier", ""), []).append(row)

    print(f"质量分层六列填充率自检（工作流 §5.7）｜分层表 {total} 行")
    for column in MISSING_COLUMNS:
        filled = sum(1 for row in rows if (row.get(column) or "").strip())
        mark = "" if filled else "  ← **整列为空**"
        print(f"  {column:<20} 非空 {filled:>3}/{total}{mark}")

    # 两个有硬性依赖的子集单独报：它们缺列时会直接让某条规则无从校验。
    l1 = by_tier.get("L1", [])
    l3 = by_tier.get("L3", [])
    l1_filled = sum(1 for row in l1 if (row.get("q2_erosion_paths") or "").strip())
    l3_filled = sum(1 for row in l3 if (row.get("tactical_thesis") or "").strip())
    print(f"  → §5.7 L1 侵蚀路径载体：L1 {l1_filled}/{len(l1)} 行有 q2_erosion_paths")
    print(f"  → L3 战术理由（买入闸门读取）：L3 {l3_filled}/{len(l3)} 行有 tactical_thesis")


def main() -> int:
    parser = argparse.ArgumentParser(description="补建质量分层六列并自检（OI-024）")
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--check", action="store_true", help="只打印填充率，不写回")
    args = parser.parse_args()

    with args.tiers.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)

    if args.check:
        report_fill_rates(rows)
        return 0

    fields = ensure_columns(rows, fields)
    filled = transcribe_erosion_paths(rows)
    with args.tiers.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"已建列 {len(MISSING_COLUMNS)} 个；本次转录 q2_erosion_paths {filled} 行")
    report_fill_rates(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
