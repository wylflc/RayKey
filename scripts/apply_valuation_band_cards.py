#!/usr/bin/env python3
"""Merge the 建带卡 draft + tag remap into the valuation table (工作流 v1.30 重建).

What this writes:

* `quality_tier`  ← 分层表（修 OI-003 的数据半边：估值表自带的旧五档会让 L4 行被池物化静默丢弃）
* `strategy_tag`  ← §6.5.0 判定顺序重贴的十一类标签
* 建带卡十二字段 ← `valuation_band_cards.csv`
* `fair_price_low/high` ← 按 §6.5.1 复算的模型带
* `valuation_tier` ← §6.2.1.6 现价对带的位置（审定档 = 建带当日按同一规则算出的档）

锚定量取不到（外部取证缺失或研报覆盖 <3 家）的行按 §6.5.2.1 判**无法估值**并清空带
——不得用近似值凑数，更不得退回通用系数带。

Usage::

    python3 scripts/apply_valuation_band_cards.py --as-of 2026-08-01 --quotes fetch
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402

from a_share_quotes import fetch_spot_quotes  # noqa: E402
from build_a_share_core_valuation_pool import effective_valuation_tier  # noqa: E402
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
TAGS = ROOT / "data/interim/strategy_tag_map.csv"
CARDS = ROOT / "data/interim/valuation_band_cards.csv"

TAG_NAMES = {
    "A": "A-现金流复利型",
    "C": "C-GARP成长型",
    "D": "D-产业链爆发/关键瓶颈型",
    "E": "E-落难白马型",
    "F": "F-资源NAV型",
    "H": "H-成本曲线周期型",
    "J": "J-金融资本型",
    "K": "K-稳态现金分配型",
    "M": "M-管线/研发资产型",
    "N": "N-订阅/递延收入型",
    "P": "P-在手订单兑现型",
}

CARD_FIELDS = [
    "anchor_metric", "anchor_value", "anchor_scope", "anchor_basis",
    "multiple_or_rate", "multiple_source", "band_low_coef", "band_high_coef",
    "shares_out", "band_derivation", "band_sensitivity", "band_fragile",
    "growth_option_value", "growth_option_share", "growth_option_evidence_level",
    "growth_option_probability", "growth_option_milestones",
    "base_band_low", "base_band_high",
    "anchor_quality", "upgrade_path", "band_is_floor", "cycle_assumption", "scenario_band_low", "scenario_band_high", "cycle_note", "implied_excess_years", "multiple_regime_flag", "implied_return", "implied_return_tier", "manual_verdict",
]


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"
REPORT_TYPE_LABEL = {"年报": "年报", "中报": "中报", "一季报": "一季报", "三季报": "三季报"}


def evidence_cutoff(code: str) -> tuple[str, str]:
    """证据文件里**最新披露的公告日与类型**（v1.42）。

    此前 `evidence_available_at` / `valuation_evidence_event` 从不由流水线刷新——早期用
    一次性脚本回填后就冻住了，导致每次重新取证都对 §7.5.5 待复核队列不可见：证据里已有
    7 月中报/预告，账面仍写 4 月一季报，队列因此永远清不掉（判例：中国神华证据 07-15 /
    账面 04-25，宁德时代 07-25 / 04-16，金山办公 07-29 / 04-24）。
    """
    path = EVIDENCE_DIR / f"{code}.json"
    if not path.exists():
        return "", ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                     # noqa: BLE001
        return "", ""
    # 三元组排序键 (公告日, 报告期, 标签)：**同一天披露多份时按报告期新旧决定**，
    # 不能靠标签字符串序。判例：泸州老窖 2026-04-29 同日披露年报与一季报，按字符串序
    # 「年报」>「一季报」，池 MD 因此把估值事件写成「年报」，而实际最新报告期是一季报。
    candidates: list[tuple[str, str, str]] = []
    for period in data.get("finance_periods") or []:
        if period.get("NOTICE_DATE"):
            label = REPORT_TYPE_LABEL.get(period.get("REPORT_TYPE"), period.get("REPORT_TYPE") or "定期报告")
            candidates.append((period["NOTICE_DATE"][:10], (period.get("REPORT_DATE") or "")[:10], label))
    for item in data.get("performance_express") or []:
        if item.get("NOTICE_DATE"):
            candidates.append((item["NOTICE_DATE"][:10], (item.get("REPORT_DATE") or "")[:10], "业绩快报"))
    for item in data.get("performance_predicts") or []:
        if item.get("NOTICE_DATE"):
            candidates.append((item["NOTICE_DATE"][:10], (item.get("REPORT_DATE") or "")[:10], "业绩预告"))
    if not candidates:
        return "", ""
    best = max(candidates)
    return best[0], best[2]


def exchange_of(code: str) -> str:
    return "SH" if code[0] == "6" else "SZ"


def main() -> int:
    parser = argparse.ArgumentParser(description="把建带卡与标签重映射合并回估值表")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--quotes", choices=["fetch", "skip"], default="fetch")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = read(VALUATION)
    tiers = {r["security_code"].zfill(6): r.get("quality_tier", "") for r in read(TIERS)}
    tags = {r["security_code"].zfill(6): r for r in read(TAGS)}
    cards = {r["security_code"].zfill(6): r for r in read(CARDS)}

    quotes: dict[str, dict] = {}
    if args.quotes == "fetch":
        items = [(r["security_code"].zfill(6), exchange_of(r["security_code"].zfill(6))) for r in rows]
        quotes = fetch_spot_quotes(items)
        print(f"行情：取到 {len(quotes)}/{len(items)} 只（{args.as_of}）")

    fieldnames = list(rows[0].keys())
    for field in CARD_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    stats = {"band": 0, "unvaluable": 0, "tier_synced": 0, "tag_changed": 0}
    tier_moves: list[str] = []
    for row in rows:
        code = row["security_code"].zfill(6)
        card, tag = cards.get(code, {}), tags.get(code, {})

        new_tier = tiers.get(code)
        if new_tier and new_tier != row.get("quality_tier"):
            row["quality_tier"] = new_tier
            stats["tier_synced"] += 1

        letter = (tag.get("strategy_tag_letter") or "").strip().upper()
        if letter in TAG_NAMES and TAG_NAMES[letter] != row.get("strategy_tag"):
            row["strategy_tag"] = TAG_NAMES[letter]
            stats["tag_changed"] += 1

        quote = quotes.get(code) or {}
        price = quote.get("price")
        if price:
            row["current_price"] = f"{price}"
            row["valuation_price_as_of"] = args.as_of
            if quote.get("pe_ttm") is not None:
                row["pe_ttm"] = f"{quote['pe_ttm']}"
            if quote.get("pb") is not None:
                row["pb"] = f"{quote['pb']}"
            if quote.get("market_cap_yi") is not None:
                row["total_market_cap_bn"] = f"{float(quote['market_cap_yi']) / 10:.4f}"
        price = price or float(row.get("current_price") or 0) or None

        for field in CARD_FIELDS:
            row.setdefault(field, "")

        low, high = card.get("fair_price_low"), card.get("fair_price_high")
        if low and high:
            for field in CARD_FIELDS:
                if card.get(field):
                    row[field] = card[field]
            row["fair_price_low"], row["fair_price_high"] = low, high
            row["base_band_low"], row["base_band_high"] = low, high   # 本轮未计入成长期权
            row["band_derivation"] = "model"
            row["fair_price_basis"] = (card.get("anchor_basis") or "")[:400]
            previous = row.get("valuation_tier", "")
            tier = effective_valuation_tier(price, float(low), float(high)) or previous
            row["valuation_tier"] = tier
            if tier != previous:
                tier_moves.append(f"{code}{row.get('security_name','')} {previous}→{tier}")
            stats["band"] += 1
        else:
            reason = card.get("needs_external") or card.get("note") or "锚定量不可得"
            row["valuation_tier"] = "无法估值"
            row["fair_price_low"] = row["fair_price_high"] = ""
            row["base_band_low"] = row["base_band_high"] = ""
            row["band_derivation"] = ""
            row["anchor_metric"] = card.get("anchor_metric", "")
            row["fair_price_basis"] = f"§6.5.2.1 锚定量不可得，判无法估值：{reason}"
            stats["unvaluable"] += 1

        cutoff_date, cutoff_event = evidence_cutoff(code)
        if cutoff_date:
            row["evidence_available_at"] = cutoff_date
            row["valuation_evidence_event"] = cutoff_event
            # 复核日按实际证据日回填：设为今日会让 §7.5.5 队列静默为空（安全方向是宁可多入队列）
            row["valuation_reviewed_at"] = cutoff_date
        else:
            row["valuation_reviewed_at"] = args.as_of
        row["valuation_method"] = f"工作流 v1.30 全量重建（{TAG_NAMES.get(letter, letter)}）"

    if args.dry_run:
        print("dry-run，未写文件")
    else:
        with VALUATION.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        append_decision_log(
            args.log_file,
            [{
                "logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "workflow_stage": "valuation_screen",
                "as_of": args.as_of,
                "decision_type": "valuation_rebuild",
                "decision_result": "rebuilt",
                "summary_reason": (
                    f"v1.30 全量重建：{len(rows)} 家中 {stats['band']} 家算出模型带、"
                    f"{stats['unvaluable']} 家判无法估值（锚定量不可得）；"
                    f"标签重贴 {stats['tag_changed']} 家、分层同步 {stats['tier_synced']} 家；"
                    f"审定档变化 {len(tier_moves)} 家"
                ),
                "input_files": f"{CARDS};{TAGS};{TIERS}",
                "output_file": str(VALUATION),
                "operator_or_script": "scripts/apply_valuation_band_cards.py",
                "workflow_version": WORKFLOW_VERSION,
            }],
        )

    print(f"重建 {args.as_of}：{len(rows)} 家")
    print(f"  模型带算出   {stats['band']}")
    print(f"  判无法估值   {stats['unvaluable']}")
    print(f"  标签重贴     {stats['tag_changed']}")
    print(f"  分层同步     {stats['tier_synced']}（修 OI-003 数据半边）")
    print(f"  审定档变化   {len(tier_moves)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
