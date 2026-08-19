#!/usr/bin/env python3
"""从 a_share_valuation_dossiers.csv 渲染每家公司的 README.md（§6.5.2 主分析文档）。

CSV 是机器可读的唯一真值来源；README 是人读正文，章节顺序固定、不得逐票自由发挥
（§6.5.2「格式统一」）。本脚本把这一条从约定变成可复算的渲染，避免逐份手写产生漂移。

用法：python3 scripts/build_company_dossier_readmes.py [--check]
  --check 只比对不写盘，有差异时以退出码 1 结束。
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"

HEADER = """# {name}（{code}）估值档案

> §6.5.2 逐票估值档案**主分析文档**。**目的：确定本公司的合理估值区间，用于判定股价低估/高估程度。**
> 带的机器可读副本在 `data/processed/a_share_valuation_dossiers.csv`（建带引擎只读该 CSV），两者须一致。
> {bespoke_line}
> **更新义务（§7.4.1）**：定期报告／业绩预告快报／研报／高频经营数据／产业政策／技术发布任一变化 →
> 先更新本档、再重算带、并把 `reviewed_at` 改为当日。

| 项 | 值 |
| --- | --- |
| 质量分层 | {tier_line} |
| 行业分类标签 | {tag}（**仅作分类，不再决定估值方法**） |
| 合理价区间 | **{band_low} ~ {band_high}** |
| 估值方法 | {band_method} |
| 盈利锚 | {anchor_line} |
| 本档更新日 | **{reviewed_at}**｜定案：{decided_by} |
"""

FOOTER = """
## 附：证据来源

**结构化证据**：`data/interim/valuation_evidence/<代码>.json`（东财接口：40 期财报、逐份研报一致预期
`ycmx`、业绩预告/快报、历史估值分位；含 `retrieved_at_utc` 与 `source_urls`，可复算）。
**人工取证**：接口不提供的输入（储量、在手订单、管线阶段、分红预案、高频经营数据）由复核者检索后
写入同一 JSON 的 `manual_evidence`（逐条含录入日/类型/期间/标题/来源URL/摘要/用途），每轮抓取结转不清空。
研报逐份跟踪见 `research_ledger.md`（§6.6.1 台账口径，若已建立）。
**v2.07 起不再设 `sources/` 原件目录**——东财无原件下载接口，该机制成文后执行 0 次（§6.5.2）。
"""

BESPOKE_ON = "`bespoke = true`——带只由本档给出，通用十类模型不参与计算。"
BESPOKE_OFF = "`bespoke = false`——本档只补充跟踪指标与复核触发，带仍由通用模型给出。"


def bullets(raw: str, seps: str = "；;") -> list[str]:
    """把 CSV 里以 ；/; 分隔的字段拆成条目。"""
    text = (raw or "").strip()
    if not text:
        return []
    for sep in seps[1:]:
        text = text.replace(sep, seps[0])
    return [item.strip() for item in text.split(seps[0]) if item.strip()]


def render(row: dict, pool: dict) -> str:
    code = row["security_code"]
    meta = pool.get(code, {})
    tier = meta.get("quality_tier", "")
    score = meta.get("quality_score", "")
    tier_line = f"{tier}（参考分 {score}）" if tier and score else (tier or "—")
    anchor = (row.get("anchor_earnings_yi") or "").strip()
    anchor_line = f"{anchor} 亿元" if anchor else "—（非盈利口径）"

    parts = [HEADER.format(
        name=row["security_name"],
        code=code,
        bespoke_line=BESPOKE_ON if str(row.get("bespoke", "")).strip().lower() == "true" else BESPOKE_OFF,
        tier_line=tier_line,
        tag=meta.get("strategy_tag", "—"),
        band_low=row["band_low"],
        band_high=row["band_high"],
        band_method=row["band_method"],
        anchor_line=anchor_line,
        reviewed_at=row["reviewed_at"],
        decided_by=row["decided_by"],
    )]

    notes = (row.get("notes") or "").strip()
    if notes:
        parts.append(f"\n## 一、为什么脱离通用模型\n\n{notes}\n")
    parts.append(f"\n## 二、带的推导（须可复算）\n\n{row['band_derivation'].strip()}\n")

    override = (row.get("runrate_override_reason") or "").strip()
    if override:
        parts.append(f"\n## 三、§6.5.4 运行率不变量\n\n{override}\n")

    sections = [
        ("四、下一个业绩核对点", row.get("next_earnings_check"), "；;"),
        ("五、高频/行业跟踪指标（不进财报但决定结论）", row.get("hf_indicators"), "｜|"),
        ("六、财务跟踪指标", row.get("key_metrics"), ";；"),
        ("七、复核触发条件", row.get("review_triggers"), "；;"),
    ]
    for title, raw, seps in sections:
        items = bullets(raw, seps)
        if not items:
            continue
        parts.append(f"\n## {title}\n\n" + "\n".join(f"- {item}" for item in items) + "\n")

    implied = (row.get("implied_growth_years") or "").strip()
    if implied:
        parts.append(f"\n## 八、现价隐含了什么\n\n{implied}\n")

    parts.append(FOOTER)
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只比对不写盘")
    args = parser.parse_args()

    with POOL.open(encoding="utf-8-sig") as handle:
        pool = {r["security_code"]: r for r in csv.DictReader(handle)}
    with DOSSIERS.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    changed, missing_dir = [], []
    for row in rows:
        target = ROOT / (row.get("dossier_dir") or "").strip()
        if not row.get("dossier_dir"):
            missing_dir.append(row["security_code"])
            continue
        target.mkdir(parents=True, exist_ok=True)
        path = target / "README.md"
        text = render(row, pool)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            changed.append(row["security_code"])
            if not args.check:
                path.write_text(text, encoding="utf-8")

    print(f"档案 {len(rows)} 份，{'需更新' if args.check else '已写入'} {len(changed)} 份")
    if changed:
        print("  " + " ".join(changed[:40]) + (" …" if len(changed) > 40 else ""))
    if missing_dir:
        print(f"  ❌ 缺 dossier_dir：{' '.join(missing_dir)}")
        return 1
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    sys.exit(main())
