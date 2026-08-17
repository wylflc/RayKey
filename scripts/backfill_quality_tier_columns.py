#!/usr/bin/env python3
"""补建质量分层的六个研究字段，并打印填充率自检（结 OI-024）。

登记的缺陷
----------
旧版分层表定义了 `q1_reason`／`q2_moat_type`／`q2_erosion_paths`／
`q3_reason`／`q4_reason`／`tactical_thesis`，但 `a_share_watchlist_quality_tiers.csv`
的 261 行中**这六列根本不存在**，属 §15.2 第 2 条「成文未落地」。

**后果不对称**，两处最要紧：

* `q2_erosion_paths` 缺列 = 工作流 §5.7 的 L1 侵蚀路径判据没有结构化载体。该节要求否决必须
  逐条写明四判据，而判据写在自由文本里就无法被任何校验检查——宁德时代的误否决
  （v1.40 前判 L2）正是这么产生的。
* `tactical_thesis` 只保留为研究字段，不产生估值或交易资格；交易统一按工作流 §9.7。

本脚本做什么、不做什么
----------------------
**做**：①把六列建出来；②把 `q2_erosion_paths` 从 `moat_summary` 的「前瞻侵蚀：」段
**转录**过来（实测 260/261 行有该段），命中 `erosion_path` 旗标的行同时带上旗标里的
概率标注；③打印六列各自的非空行数（凡新增列，跑完必须核对非空
行数——四次静默失效的共同签名就是「某列整体为空而无人察觉」）。

**不做**：不给任何一列打分、不改任何档位。②是**转录**（同一句话换个位置存），不是
判断；`q2_moat_type` 与 `tactical_thesis` 这类需要判断的内容由模型逐票回填，
工作流 §5.7 禁止关键词脚本自动决定层级。

幂等：已非空的单元格一律不覆盖，可反复运行。

用法::

    python3 scripts/backfill_quality_tier_columns.py            # 写回并打印填充率
    python3 scripts/backfill_quality_tier_columns.py --check    # 只打印填充率
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
# 正是 §15.2 第 3 条点名的「某列本该命中却没写」。
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
    print(f"  → L3 研究备注（不影响交易）：L3 {l3_filled}/{len(l3)} 行有 tactical_thesis")


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
