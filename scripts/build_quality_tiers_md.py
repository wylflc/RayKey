#!/usr/bin/env python3
"""Render the quality tier detail file from the tier CSV (工作流 §5.7).

**不再是 000_ 用户必读文件（2026-08-01）**：池阅读版自 v1.39 起已带质量档与参考分，
本文件唯一的独有内容是 `tier_reason`（平均 25 字，多为模板句）。保留为分层明细的
可查文件，去掉 000_ 前缀——该前缀按 CLAUDE.md 专留给用户直接打开阅读的文件。

The MD used to be maintained by hand and drifted badly — it still described the
v17 five-tier ladder (L1-L5) months after v1.27 replaced it with three tiers,
and its stated distribution (L1 24 / L2 158 / L3 67 / L4 12) no longer matched
the CSV (L1 21 / L2 231 / L3 9). Generating it removes that failure mode: the
reading file can no longer disagree with the data it claims to summarise.

Usage::

    python3 scripts/build_quality_tiers_md.py --as-of 2026-08-01
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
TAGS = ROOT / "data/interim/strategy_tag_map.csv"
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
OUT = ROOT / "data/processed/a_share_watchlist_quality_tiers.md"

TIER_HEADS = {
    "L1": ("L1 强护城河", "门槛由买不到的要素与压不掉的时间构成，未来 2-3 年无可见侵蚀路径，且生意模式本身不塌陷。允许最低的安全边际要求。"),
    "L2": ("L2 中护城河", "资本复制测试通过，但存在可见侵蚀路径、明确同业竞争，或未过 L1 任一通道。**默认档**，多数值得关注公司在此。"),
    "L3": ("L3 弱护城河", "没有任何一项足够强可倚仗，要求最深的安全边际。"),
}


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description="渲染质量分层阅读版 MD")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    tiers = read(TIERS)
    # 渲染前检查质量研究字段填充率（OI-024），避免整列缺失长期不可见。
    from backfill_quality_tier_columns import report_fill_rates
    report_fill_rates(tiers)
    tags = {r["security_code"].zfill(6): r for r in read(TAGS)}
    pool = {r["security_code"].zfill(6): r for r in read(POOL)} if POOL.exists() else {}
    counts = Counter(r.get("quality_tier", "") for r in tiers)

    lines = [
        "# A股值得关注公司质量分层（阅读版）",
        "",
        f"- 生成日期：{args.as_of}｜由 `scripts/build_quality_tiers_md.py` 渲染，不手工维护",
        "- 口径：工作流 §5.7 三档分层；版本读取工作流第 1 行，不在派生文件固化",
        f"- 覆盖：`worth_attention` 全部 {len(tiers)} 家；分布 "
        + " / ".join(f"{k} {counts[k]}" for k in ("L1", "L2", "L3") if counts[k]),
        "- **分层只看业务质量，不含估值或交易结论**；不配给关注名额，名单进出由 `attention_class` 独立判定。",
        "- **策略标签只作研究分类与展示**；生产估值统一按工作流 §6.5，交易只认 §9.3。",
        "- 层级按工作流 §5.7 的规则逐家判定，不按预设分布调整。",
        "",
    ]

    for tier in ("L1", "L2", "L3"):
        rows = [r for r in tiers if r.get("quality_tier") == tier]
        if not rows:
            continue
        title, desc = TIER_HEADS[tier]
        lines += [f"## {title} — {len(rows)}家", "", desc, "",
                  "| 代码 | 名称 | 策略标签 | 定档理由（摘） |",
                  "| --- | --- | --- | --- |"]
        for row in sorted(rows, key=lambda r: r["security_code"]):
            code = row["security_code"].zfill(6)
            tag = pool.get(code, {}).get("strategy_tag") or tags.get(code, {}).get("strategy_tag_letter", "")
            reason = (row.get("tier_reason") or row.get("moat_summary") or "").replace("\n", " ").replace("|", "／")
            # `tier_reason` 的逐条对照可能超过表格可读宽度。
            # 截断保留，但必须**可见**——静默截断会让 MD 声称汇总了它其实没显示的依据。
            if len(reason) > 150:
                reason = reason[:150] + "…（全文见 CSV `tier_reason`）"
            lines.append(f"| {code} | {row.get('security_name','')} | {tag} | {reason} |")
        lines.append("")

    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {args.out}（{len(tiers)} 家，"
          + " / ".join(f"{k} {counts[k]}" for k in ("L1", "L2", "L3") if counts[k]) + "）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
