#!/usr/bin/env python3
"""Merge the 建带卡 draft + tag remap into the valuation table（工作流 §6.7 第 5 步）.

What this writes:

* `quality_tier`  ← 分层表（修 OI-003 的数据半边：估值表自带的旧五档会让 L4 行被池物化静默丢弃）
* `strategy_tag`  ← §6.5 判定顺序重贴的十一类标签
* 建带卡十二字段 ← `valuation_band_cards.csv`
* `fair_price_low/high` ← 按 §6.5.1 复算的模型带
* `valuation_tier` ← §6.2 现价对带的位置（审定档 = 建带当日按同一规则算出的档）

锚定量取不到（外部取证缺失或研报覆盖 <3 家）的行按 §6.5.2.4 判**无法估值**并清空带
——不得用近似值凑数，更不得退回通用系数带。

Usage::

    python3 scripts/apply_valuation_band_cards.py --signal-date 2026-08-01 --quotes fetch
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
from a_share_signal_dates import evidence_iso_for_signal  # noqa: E402
from build_a_share_core_valuation_pool import effective_valuation_tier  # noqa: E402
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
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
    "anchor_quality", "upgrade_path", "band_is_floor", "anchor_vintage", "method_divergence", "runrate_check", "cycle_assumption", "scenario_band_low", "scenario_band_high", "cycle_note", "implied_excess_years", "multiple_regime_flag", "implied_return", "implied_return_tier", "manual_verdict",
]

# 成长期权是人工复核（§6.6）逐票填的判断，建带卡不产出这几列（v1.46，OI-017）。
# 它们必须排除在「整列覆盖」之外，否则每轮 apply 都会把人工填的期权清空。
HUMAN_CURATED_FIELDS = [
    "growth_option_value", "growth_option_share", "growth_option_evidence_level",
    "growth_option_probability", "growth_option_milestones",
]
CARD_OWNED_FIELDS = [f for f in CARD_FIELDS if f not in HUMAN_CURATED_FIELDS]


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


EVIDENCE_DIR = ROOT / "data/interim/valuation_evidence"
REPORT_TYPE_LABEL = {"年报": "年报", "中报": "中报", "一季报": "一季报", "三季报": "三季报"}


def evidence_cutoff(code: str) -> tuple[str, str]:
    """证据文件里**最新披露的公告日与类型**（v1.42）。

    此前 `evidence_available_at` / `valuation_evidence_event` 从不由流水线刷新——早期用
    一次性脚本回填后就冻住了，导致每次重新取证都对 §7.5.1 待复核队列不可见：证据里已有
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


def quote_date(quote_time: object, fallback: str) -> str:
    """Return the provider's actual trading date, not the evidence cutoff date."""
    raw = str(quote_time or "").strip()
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return fallback


REPORT_EVENT = {"03-31": "一季报", "06-30": "中报", "09-30": "三季报", "12-31": "年报"}


# **生产模型带的唯一落点**（§2 固定产物表）。此前这里指向 `data/interim/pool_model_bands.csv`
# ——那是 v2.72 时代的中间物化文件，已在 2026-08-17 修 dossier 污染时删除。文件一删，
# 下面的 `if not path.exists(): return best` 就让整张表**静默退回 `evidence_cutoff()` 兜底**，
# 于是「估值时间/估值事件」两列改读 `valuation_evidence/*.json` 那份 8-04 的旧证据快照。
# 后果：贵州茅台 8-15 披露半年报、带已按半年报重算为 667.21-815.48，而池 MD 仍显示
# 「2026-04-25 一季报」。**空字典没有任何告警，与「模型带全部缺失」不可区分**——这正是
# 本仓库反复踩到的静默失效签名，故本函数改为**读不到就硬失败**。
MODEL_BANDS_PATH = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"


def _load_model_bands() -> dict:
    """模型带里每只最新可用的一条。取值口径与 `apply_model_bands_to_dossiers.py` 完全一致
    （`(available_at, report_date)` 双键），否则两处会给出不同的报告期。"""
    path = MODEL_BANDS_PATH
    best: dict[str, dict] = {}
    if not path.exists():
        raise SystemExit(
            f"缺少生产模型带 {path.relative_to(ROOT)}——先跑 §6.7 第 4 步 "
            f"`build_pool_model_bands.py`。**不可静默继续**：模型带缺失时"
            "「估值时间/估值事件」会退回陈旧证据快照，读者据此以为带没跟上最新财报。"
        )
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("status") != "ok":
                continue
            code = r["security_code"]
            key = (r.get("available_at", ""), r.get("report_date", ""))
            if code not in best or key > (best[code]["available_at"], best[code]["report_date"]):
                best[code] = r
    if not best:
        raise SystemExit(f"{path.relative_to(ROOT)} 里没有 status=ok 的模型带——同上，不可静默继续。")
    return best


MODEL_BANDS = _load_model_bands()


def _load_model_evaluated(path: Path = MODEL_BANDS_PATH) -> dict[str, str]:
    """各代码的 `model_evaluated_at`（含 status 非 ok 的行，§6.5.2.4 主体重置后无 ok 带时仍要推进复核日）。"""
    out: dict[str, str] = {}
    if path is None or not Path(path).exists():
        return out
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ev = max((r.get("model_evaluated_at") or "")[:10], (r.get("available_at") or "")[:10])
            if ev and ev > out.get(r["security_code"], ""):
                out[r["security_code"]] = ev
    return out


MODEL_EVALUATED = _load_model_evaluated()


def seed_new_pool_rows(rows: list[dict], tiers: dict[str, str], cards: dict[str, dict]) -> list[tuple[str, str]]:
    """给分层表里已定档、但估值表还没有行的 `worth_attention` 成员补一行占位。

    只填身份与带；价格、档位、PE/PB 等由本脚本随后的主循环统一写入，与既有行同一口径。
    """
    known = {r["security_code"].zfill(6) for r in rows}
    template = list(rows[0].keys()) if rows else []
    dossiers = {r["security_code"].zfill(6): r
                for r in read(DOSSIERS)
                if (r.get("dossier_status") or "").strip() == "active"}
    seeded: list[tuple[str, str]] = []
    for code, tier in sorted(tiers.items()):
        if code in known or tier not in ("L1", "L2", "L3"):
            continue
        card, doc = cards.get(code), dossiers.get(code)
        if not card or not doc:
            continue
        low, high = card.get("band_low") or doc.get("band_low"), card.get("band_high") or doc.get("band_high")
        if not low or not high:
            continue
        row = {field: "" for field in template}
        row.update({
            "security_code": code,
            "security_name": doc.get("security_name", ""),
            "quality_tier": tier,
            "valuation_method": "内在价值模型（§6.5.2.3，v2.72 起唯一带来源）",
            "fair_price_low": low,
            "fair_price_high": high,
            "valuation_reason": "新入 worth_attention（§5.5 迁移），带由 §6.7 链机械生成",
        })
        rows.append(row)
        seeded.append((code, row["security_name"]))
    return seeded


def main() -> int:
    parser = argparse.ArgumentParser(description="把建带卡与标签重映射合并回估值表")
    parser.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    parser.add_argument("--quotes", choices=["fetch", "skip"], default="fetch")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    args.as_of = evidence_iso_for_signal(args.signal_date)

    rows = read(VALUATION)
    tiers = {r["security_code"].zfill(6): r.get("quality_tier", "") for r in read(TIERS)}
    tags = {r["security_code"].zfill(6): r for r in read(TAGS)}
    cards = {r["security_code"].zfill(6): r for r in read(CARDS)}

    # 新入池公司补行：本表此前只更新已有行、从不新增，`worth_attention` 新成员因而
    # 拿不到估值行，核心池与每日扫描都看不见它（2026-08-30 OI-036 升池时暴露）。
    # 补行条件是三者齐备——分层表已定 L1-L3、已有 active 逐票档案（§6.5.2）、建带卡已算出带；
    # 缺任一项不补，由 §6.7 的既有告警暴露。
    seeded = seed_new_pool_rows(rows, tiers, cards)
    if seeded:
        print(f"  新入池补行 {len(seeded)} 只：" + "、".join(f"{c} {n}" for c, n in seeded))

    quotes: dict[str, dict] = {}
    if args.quotes == "fetch":
        items = [(r["security_code"].zfill(6), exchange_of(r["security_code"].zfill(6))) for r in rows]
        quotes = fetch_spot_quotes(items)
        print(f"行情：取到 {len(quotes)}/{len(items)} 只（信号日 {args.signal_date}，证据日 {args.as_of}）")

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
            # The derived evidence date is the cutoff (§6.7), which can be the next
            # calendar day for an evening filing.  The quote may still be the
            # previous trading day's close, so stamp it from Tencent field 30.
            row["valuation_price_as_of"] = quote_date(quote.get("quote_time"), args.signal_date)
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
            # v1.46：建带卡自有的列**整列覆盖，包括清空**。原写法是 `if card.get(field)`
            # ——只写非空值，于是建带卡把某个标记**去掉**时下游永远清不掉。判例（OI-017）：
            # v1.46 把 D primary 的 `band_is_floor` 正确移除后，建带卡 88→23，而估值表与池
            # 仍是 88，65 行继续免除提醒卖出，改动等于没生效；同批还清出紫金矿业一条
            # v1.38 era 的 `mean_reversion_assumed` 残留——它的带早已改走 F-2 的 PB 口径
            # （锚是每股净资产，运行率校验按定义不适用），标记却一直留着抑制卖出提醒。
            # 带每轮全量重算，卡即这些列的唯一真值来源。
            for field in CARD_OWNED_FIELDS:
                row[field] = card.get(field, "")
            # 人工策展列（成长期权，§6.6 人工复核）不由建带卡产出，只在卡确有值时覆盖——
            # 否则每轮 apply 都会把人工复核逐票填进去的期权抹掉。
            for field in HUMAN_CURATED_FIELDS:
                if card.get(field):
                    row[field] = card[field]
            row["fair_price_low"], row["fair_price_high"] = low, high
            row["base_band_low"], row["base_band_high"] = low, high   # 本轮未计入成长期权
            # 建带卡自报口径优先（§6.5.2 的 `dossier` 必须保留到下游，否则阅读版的
            # 「（档）」标记与池的档案识别都拿不到它）；仅在卡未标注时兜底为 model。
            row["band_derivation"] = card.get("band_derivation") or "model"
            row["fair_price_basis"] = (card.get("anchor_basis") or "")[:400]
            previous = row.get("valuation_tier", "")
            tier = effective_valuation_tier(price, float(low), float(high)) or previous
            row["valuation_tier"] = tier
            if tier != previous:
                tier_moves.append(f"{code}{row.get('security_name','')} {previous}→{tier}")
            stats["band"] += 1
        else:
            reason = card.get("needs_external") or card.get("note") or "锚定量不可得或模型判不可估"
            row["valuation_tier"] = "无法估值"
            row["fair_price_low"] = row["fair_price_high"] = ""
            row["base_band_low"] = row["base_band_high"] = ""
            row["band_derivation"] = ""
            row["anchor_metric"] = card.get("anchor_metric", "")
            # 两种情形都落这里：①建档未完成（锚定量不可得）；②v4.22 统一口径——模型判
            # 不可估或模型带过旧（档案带已被清空，OI-068）。带显示 —，无 P/V，不进 §9.3。
            row["fair_price_basis"] = f"无法估值（§6.5.2.4 统一口径）：{reason}"
            stats["unvaluable"] += 1

        # v2.79：模型带行的「估值时间/估值事件」必须取**模型带的报告期**，不是取数证据的时点。
        # v2.72 换模型带后带由逐季财务算出，而 `evidence_cutoff()` 读的是 `valuation_evidence/`
        # 里上一次证据抓取的截止期——两者已经不是同一件事。判例：宇通客车 2026-08-10 的带来自
        # 2026-06-30 中报，池 MD 却显示「2026-04-28 一季报」，读者据此会以为带没跟上中报。
        mb = MODEL_BANDS.get(code)
        if mb:
            row["evidence_available_at"] = mb["available_at"][:10]
            row["valuation_evidence_event"] = REPORT_EVENT.get(mb["report_date"][5:10], "定期报告")
            # 复核日 = 模型最近评估过的报告期可得日（含护栏拒绝行，`model_evaluated_at`）：
            # 采纳带停在更早 ok 行（护栏连续拒绝／无法估值）时，已评估的新报告期不再重复入队。
            row["valuation_reviewed_at"] = max(mb["available_at"][:10],
                                               (mb.get("model_evaluated_at") or "")[:10])
            row["valuation_method"] = "内在价值模型（§6.5.2.3，v2.72 起唯一带来源）"
            continue
        cutoff_date, cutoff_event = evidence_cutoff(code)
        if cutoff_date:
            row["evidence_available_at"] = cutoff_date
            row["valuation_evidence_event"] = cutoff_event
            # 复核日按实际证据日回填：设为今日会让 §7.5.1 队列静默为空（安全方向是宁可多入队列）
            row["valuation_reviewed_at"] = cutoff_date
        else:
            row["valuation_reviewed_at"] = args.as_of
        ev = MODEL_EVALUATED.get(code)
        if ev and ev > (row.get("valuation_reviewed_at") or ""):
            row["valuation_reviewed_at"] = ev              # 模型已评估（含拒绝行）的报告期不再重复入队
        row["valuation_method"] = f"建带卡回写（{TAG_NAMES.get(letter, letter)}，{WORKFLOW_VERSION}）"

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
                    f"建带卡回写（{WORKFLOW_VERSION}）：{len(rows)} 家中 {stats['band']} 家算出模型带、"
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
