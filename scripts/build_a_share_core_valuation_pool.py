#!/usr/bin/env python3
"""Build the A-share core valuation pool.

Materializes ALL worth_attention L1-L4 names (v1.04) into one pool CSV/MD for
the daily scan. Since v1.05 the valuation tier is **price-auto-refreshed**
(§6.2.1.6): the displayed/effective tier is derived每日 from spot price vs the
reviewed fair band, with no manual review step — tier changes are simply
reported in the daily scan entry. Reviews (§7: reports/预告/events) change the
BAND; price changes the TIER; the §6.2.1 matrix maps tier to buy eligibility.

This script does not create new valuation opinions: the band, the reviewed
baseline tier (审定档) and reasons come from the valuation table.

Daily refresh: ``--md-only --quotes fetch`` re-renders only the reading MD
(现价/空间/PE/PB + auto tier), diffs effective tiers against the
previous snapshot (`data/interim/pool_effective_tiers.csv`) and logs one
`pool_price_refresh` summary row listing today's tier changes.

The same MD carries the 海外关注清单 appendix (§6.8): non-A-share names the user
tracks, rendered from `overseas_watchlist_valuation.csv` with the identical
§6.2.1.6 price-auto-tier logic but kept out of the pool CSV, out of the daily
volume/price scan and out of buy eligibility.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from a_share_quotes import fetch_spot_quotes
from overseas_quotes import fetch_overseas_quotes
from validate_valuation_bands import check_row as check_band_card
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/000_a_share_core_valuation_pool.md"
DEFAULT_FORECASTS = ROOT / "data/interim/a_share_earnings_forecasts.csv"
DEFAULT_DISCLOSURES = ROOT / "data/interim/a_share_report_disclosures.csv"
DEFAULT_TIER_SNAPSHOT = ROOT / "data/interim/pool_effective_tiers.csv"
DEFAULT_OVERSEAS = ROOT / "data/processed/overseas_watchlist_valuation.csv"
DEFAULT_OVERSEAS_TIER_SNAPSHOT = ROOT / "data/interim/overseas_effective_tiers.csv"
MARKET_LABELS = {"HK": "港股", "US": "美股", "KR": "韩股"}

# §6.2.1 分层×估值三态矩阵（v1.27 三档重构）：可买 / 可持有 / 提醒卖出。
TIER_ELIGIBLE_VALUATIONS = {
    "L1": {"低估", "较低估", "中性"},
    "L2": {"低估", "较低估"},
    "L3": {"低估"},
}
# 可持有：不可新建仓/加仓，已持仓不因此卖出。
TIER_HOLDABLE_VALUATIONS = {
    "L1": {"较高估"},
    "L2": {"中性"},
    "L3": {"较低估"},
}
# 提醒卖出起点（该档及以上触发 §14 估值卖出减仓梯）。
TIER_TRIM_ALERT_FROM = {"L1": "高估", "L2": "较高估", "L3": "中性"}
VALUATION_ORDER = ["低估", "较低估", "中性", "较高估", "高估"]
CORE_LAYER_TIERS = {"L1", "L2"}
WATCH_VALUATIONS = {"低估", "较低估", "中性", "较高估"}


def matrix_state(tier: str, valuation: str) -> str:
    """§6.2.1 三态：buyable / holdable / trim_alert / na。"""
    if tier not in TIER_ELIGIBLE_VALUATIONS or valuation not in VALUATION_ORDER:
        return "na"
    if valuation in TIER_ELIGIBLE_VALUATIONS[tier]:
        return "buyable"
    if valuation in TIER_HOLDABLE_VALUATIONS[tier]:
        return "holdable"
    start = TIER_TRIM_ALERT_FROM[tier]
    if VALUATION_ORDER.index(valuation) >= VALUATION_ORDER.index(start):
        return "trim_alert"
    return "na"
# §6.2.1.6 价格自动定档阈值（v1.05 初始校准，修订先改工作流）。
OVERVALUED_BAND_MULT = 1.2  # 带顶×1.2 以上 = 高估（沿 D 档 100-120% 惯例）
DEEP_UNDERVALUED_UPSIDE = 0.40  # 带底以下且空间（区间中值/现价-1）>= 40% = 低估，否则较低估
# 预告指标口径优先级：归母净利 > 扣非 > 营业收入（§6.7.8，仅作复核队列输入统计）。
FORECAST_METRIC_PRIORITY = {"004": 0, "005": 1, "006": 2}


def effective_valuation_tier(price: float | None, fair_low: float | None, fair_high: float | None) -> str | None:
    """§6.2.1.6 价格自动定档：>1.2×带顶=高估；带顶~1.2×带顶=较高估；带内=中性；
    带底以下按空间 >=40% 分低估/较低估。双向均不限幅（v1.14）——跌得够深即可高估直达低估。
    无带或无价返回 None（调用方保留存档档位，如无法估值）。"""
    if not price or fair_low is None or fair_high is None or fair_low <= 0 or fair_high <= 0:
        return None
    if price > fair_high * OVERVALUED_BAND_MULT:
        return "高估"
    if price > fair_high:
        return "较高估"
    if price >= fair_low:
        return "中性"
    mid = (fair_low + fair_high) / 2
    return "低估" if mid / price - 1 >= DEEP_UNDERVALUED_UPSIDE else "较低估"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


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
    for tier in ("L1", "L2", "L3"):
        if value.startswith(tier):
            return tier
    return value


def build_pool(
    valuation_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    as_of: str,
) -> list[dict[str, str]]:
    """物化全量 worth_attention 为单一列表（v1.05）。v1.27 三档重构：
    pool_layer 仅 core（L1/L2）/ tactical（L3）/ excluded（无法估值）——**watch_only 已退役**，
    买入端只有二态。新增 matrix_state 记录审定档口径的三态（buyable/holdable/trim_alert）；
    每日实际状态以扫描时的价格自动定档为准，本列仅作审计口径。"""
    tier_by_code = {row["security_code"].zfill(6): row for row in tier_rows}
    output: list[dict[str, str]] = []
    skipped: list[str] = []

    for row in valuation_rows:
        code = row["security_code"].zfill(6)
        tier_row = tier_by_code.get(code)
        quality_tier = normalize_quality_tier(
            row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", "")
        )
        valuation_tier = row.get("valuation_tier", "")

        if quality_tier not in TIER_ELIGIBLE_VALUATIONS:
            # OI-003：**不得静默跳过**。旧口径遇到无法归入 L1/L2/L3 的行直接 continue，
            # v1.27 三档重构后估值表仍带旧五档，12 行 L4 因此消失于池与每日扫描而无任何
            # 提示——与「全量 worth_attention 统一扫描」的意图相反。现改为计数并上报。
            skipped.append(f"{code}{row.get('security_name','')}({quality_tier or '空'})")
            continue
        state = matrix_state(quality_tier, valuation_tier)

        # §6.7 要求 10/11（v1.28）：带必须是 §6.5.1 两形态之一算出的模型带。
        # blocking（档位反推 / 已退役标签 / 复算不符）→ 降为可持有：不得新建仓加仓，
        # 但不触发 §14 提醒卖出（反推带的偏差双向，只切买入侧是唯一不制造新错误动作的过渡态）。
        # backfill（模型带、仅建带卡未回填）→ 限期登记义务，买入资格不变（同 §10.4 研究档案项）。
        band_problems, band_severity = check_band_card(row)
        # §6.5.5.1 第 3 条：下限性质的兜底带（M-2/P-2/D≤1家覆盖，明确不含管线/订单/成长）
        # 只在「连下限都便宜」时有信息量；反向读作「贵」不成立，故不触发提醒卖出。
        if str(row.get("band_is_floor", "")).strip().lower() == "true" and state == "trim_alert":
            state = "holdable"
        # §6.5.4（v1.36）：锚假设均值回归、而当前运行率显著更高的行，「贵」的结论取决于
        # 未取得的供给侧证据，不得据以发卖出提醒（同下限带处理）。
        if row.get("cycle_assumption") == "mean_reversion_assumed" and state == "trim_alert":
            state = "holdable"
        if not band_problems:
            band_status = "ok"
        elif band_severity == "blocking":
            band_status = "rebuild_required"
            if state == "buyable":
                state = "holdable"
        else:
            band_status = "backfill_due"
        # v1.27：档位决定 core/tactical，与当日估值档无关；仅「无法估值」排除。
        if state == "na":
            pool_layer = "excluded"
        else:
            pool_layer = "core" if quality_tier in CORE_LAYER_TIERS else "tactical"

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "security_name": row.get("security_name", ""),
                "exchange": infer_exchange(code, tier_row),
                "quality_tier": quality_tier,
                "quality_tier_label": row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", ""),
                "quality_score": (tier_row or {}).get("quality_score", ""),
                "pool_layer": pool_layer,
                "matrix_state": state,
                "band_derivation": row.get("band_derivation", "") or ("fallback" if band_status == "rebuild_required" else ""),
                "band_status": band_status,
                "anchor_quality": row.get("anchor_quality", ""),
                "band_is_floor": row.get("band_is_floor", ""),
                "cycle_assumption": row.get("cycle_assumption", ""),
                "scenario_band_low": row.get("scenario_band_low", ""),
                "scenario_band_high": row.get("scenario_band_high", ""),
                "upgrade_path": row.get("upgrade_path", ""),
                "strategy_tag": row.get("strategy_tag", ""),
                "valuation_tier": valuation_tier or "（空）",
                "valuation_batch_id": row.get("valuation_batch_id", ""),
                "valuation_price": row.get("current_price", ""),
                # §8.5.6 巨盘温和放量输入：估值时点总市值（十亿），扫描按现价比例折算。
                "total_market_cap_bn": row.get("total_market_cap_bn", ""),
                "fair_price_low": row.get("fair_price_low", ""),
                "fair_price_high": row.get("fair_price_high", ""),
                "fair_price_basis": row.get("fair_price_basis", ""),
                "valuation_pe_ttm": row.get("pe_ttm", ""),
                "valuation_pb": row.get("pb", ""),
                "valuation_reason": row.get("valuation_reason", ""),
                # §6.7：估值结论日原样透传；pool_as_of 只是物化日，不得当估值复核日用。
                "valuation_reviewed_at": row.get("valuation_reviewed_at", ""),
                "valuation_evidence_event": row.get("valuation_evidence_event", ""),
                "valuation_price_as_of": row.get("valuation_price_as_of", ""),
                "evidence_available_at": row.get("evidence_available_at", ""),
                "pool_as_of": as_of,
                "source_file": str(DEFAULT_VALUATION.relative_to(ROOT)),
            }
        )

    if skipped:
        print(f"⚠️ 分层不可归类被跳过 {len(skipped)} 行（OI-003）：{'、'.join(skipped[:10])}"
              + ("…" if len(skipped) > 10 else ""))
    return output


def _to_float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result


def load_forecasts(path: Path) -> dict[str, dict[str, str]]:
    """每代码取最优口径预告行：归母 > 扣非 > 营收，同口径取最新公告日；仅 is_latest=T。"""
    if not path.exists():
        return {}
    best: dict[str, dict[str, str]] = {}
    for row in load_csv(path):
        if row.get("is_latest") != "T":
            continue
        code = row["security_code"].zfill(6)
        rank = FORECAST_METRIC_PRIORITY.get(str(row.get("predict_finance_code")), 9)
        current = best.get(code)
        if current is None:
            best[code] = row
            continue
        cur_rank = FORECAST_METRIC_PRIORITY.get(str(current.get("predict_finance_code")), 9)
        if rank < cur_rank or (rank == cur_rank and row.get("notice_date", "") > current.get("notice_date", "")):
            best[code] = row
    return best


def forecasts_retrieved_on(path: Path) -> str:
    """预告物化文件的检索日（retrieved_at_utc 最大值的日期部分）；文件缺失返回空。
    §6.7.8（v1.16）：检索日早于扫描日=数据过期，须按 §9.1 步骤 0 重抓。"""
    if not path.exists():
        return ""
    stamps = [str(row.get("retrieved_at_utc") or "") for row in load_csv(path)]
    return max(stamps)[:10] if stamps else ""


DISCLOSURE_LABELS = {"periodic_report": "定期报告", "express_report": "快报"}


def load_disclosures(path: Path) -> dict[str, dict[str, str]]:
    """§6.7.9（v1.18）：每代码取 正式定期报告/业绩快报 中公告日最新的一行，
    供 §7.5.5 待复核名单判定（与预告公告日取并集后的最大者比较估值时间）。"""
    if not path.exists():
        return {}
    best: dict[str, dict[str, str]] = {}
    for row in load_csv(path):
        if row.get("disclosure_type") not in DISCLOSURE_LABELS:
            continue
        code = row["security_code"].zfill(6)
        current = best.get(code)
        if current is None or row.get("notice_date", "") > current.get("notice_date", ""):
            best[code] = row
    return best


def display_cells(row: dict[str, str], quote: dict | None) -> dict[str, object]:
    """阅读版单元格：现价/空间/PE/PB 按行情快照刷新，档位按 §6.2.1.6 价格自动定档。"""
    low = _to_float(row.get("fair_price_low"))
    high = _to_float(row.get("fair_price_high"))
    val_price = _to_float(row.get("valuation_price"))
    spot = _to_float(quote.get("price")) if quote else None
    ref_price = spot if spot else val_price

    if low is None or high is None:
        band = "—"
    else:
        band = row["fair_price_low"] if row["fair_price_low"] == row["fair_price_high"] else f"{row['fair_price_low']}-{row['fair_price_high']}"

    if low is None or high is None or not ref_price:
        upside = "—"
    else:
        pct = round(((low + high) / 2 / ref_price - 1) * 100)
        upside = "0%" if pct == 0 else f"{pct:+d}%"

    stored = str(row.get("valuation_tier", ""))
    # 无法估值无可靠带，不自动定档（§6.2.1.6）；其余按现价（缺失时按估值价）定档。
    effective = stored if stored == "无法估值" else (effective_valuation_tier(ref_price, low, high) or stored)

    spot_pe = _to_float(quote.get("pe_ttm")) if quote else None
    spot_pb = _to_float(quote.get("pb")) if quote else None
    return {
        "price": f"{spot:.2f}" if spot else "—",
        "band": band,
        "upside": upside,
        "pe": f"{spot_pe:.2f}" if spot_pe else str(row.get("valuation_pe_ttm") or "—"),
        "pb": f"{spot_pb:.2f}" if spot_pb else str(row.get("valuation_pb") or "—"),
        "effective_tier": effective,
        "valuation_cell": effective if effective == stored else f"{stored}→{effective}",
        "spot_pe": spot_pe,
    }


def format_quote_time(quotes: dict[str, dict]) -> str:
    stamps = [str(q.get("quote_time") or "") for q in quotes.values()]
    stamps = [s for s in stamps if len(s) >= 12]
    if not stamps:
        return ""
    t = max(stamps)
    return f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"


def load_tier_snapshot(path: Path, pad_code: bool = True) -> dict[str, str]:
    """pad_code=False 供海外附表快照使用（键为 `市场:代码`，不能按6位补零）。"""
    if not path.exists():
        return {}
    return {
        (row["security_code"].zfill(6) if pad_code else row["security_code"]): row.get("effective_tier", "")
        for row in load_csv(path)
    }


def write_tier_snapshot(path: Path, tiers: dict[str, tuple[str, str]], as_of: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["security_code", "security_name", "effective_tier", "as_of"])
        writer.writeheader()
        for code, (name, tier) in sorted(tiers.items()):
            writer.writerow({"security_code": code, "security_name": name, "effective_tier": tier, "as_of": as_of})


def load_overseas(path: Path) -> list[dict[str, str]]:
    """§6.8 海外关注清单：文件缺失即视为空清单（附表不渲染），不影响 A 股主表。"""
    if not path.exists():
        return []
    return [row for row in load_csv(path) if row.get("security_code")]


def _fmt_number(value: float | None, currency: str) -> str:
    """韩元等无小数币种按千分位整数展示，其余保留两位小数。"""
    if value is None:
        return "—"
    if currency == "KRW":
        return f"{value:,.0f}"
    return f"{value:.2f}"


def build_overseas_section(
    rows: list[dict[str, str]],
    quotes: dict[str, dict] | None = None,
    prev_tiers: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, object]]:
    """渲染 §6.8 海外关注清单附表：档位仍按 §6.2.1.6 现价自动定档，但不入池 CSV、
    不入每日量价扫描、无买入资格。返回 (MD 行, {'changes', 'current_tiers'})。"""
    if not rows:
        return [], {"changes": [], "current_tiers": {}}
    quotes = quotes or {}
    prev_tiers = prev_tiers or {}
    changes: list[str] = []
    current_tiers: dict[str, tuple[str, str]] = {}
    body: list[str] = []
    # 与 A 股主表一致按质量档 L1→L3 排序；稳定排序使同档内保持清单原序（港股→美股→韩股）。
    tier_rank = {tier: index for index, tier in enumerate(("L1", "L2", "L3"))}
    # v1.39：档内按**参考分**降序（§5.7 参考分只作档内排序展示，不改变矩阵资格）。
    rows = sorted(
        rows,
        key=lambda row: (
            tier_rank.get(normalize_quality_tier(str(row.get("quality_tier", ""))), 99),
            -(_to_float(row.get("quality_score")) or 0.0),
        ),
    )
    for row in rows:
        market = str(row.get("market_type", "")).upper()
        code = row["security_code"]
        key = f"{market}:{code}"
        quote = quotes.get(key)
        currency = str((quote or {}).get("currency") or row.get("currency") or "")
        cells = display_cells(row, quote)
        effective = str(cells["effective_tier"])
        current_tiers[key] = (row["security_name"], effective)
        prev = prev_tiers.get(key)
        if prev and prev != effective:
            changes.append(f"{row['security_name']} {prev}→{effective}")
        spot = _to_float((quote or {}).get("price"))
        price_cell = _fmt_number(spot if spot else _to_float(row.get("valuation_price")), currency)
        low, high = _to_float(row.get("fair_price_low")), _to_float(row.get("fair_price_high"))
        if low is None or high is None:
            band_cell = "—"
        elif currency == "KRW":
            band_cell = f"{_fmt_number(low, currency)}-{_fmt_number(high, currency)}"
        else:
            # 与 A 股主表一致：带原样透传估值表字符串，不重新格式化位数。
            band_cell = f"{row['fair_price_low']}-{row['fair_price_high']}"
        body.append(
            "| {market} | {code} | {name} | {tier} | ".format(
                market=f"{MARKET_LABELS.get(market, market)}·{currency}" if currency else MARKET_LABELS.get(market, market),
                code=code,
                name=row["security_name"],
                tier=row.get("quality_tier", "—"),
            )
            + f"{cells['valuation_cell']} | {row.get('strategy_tag', '—')} | "
            + f"{price_cell} | {band_cell} | {cells['upside']} | {cells['pe']} | {cells['pb']} | "
            + f"{row.get('valuation_reviewed_at') or '—'} | {row.get('valuation_evidence_event') or '—'} |"
        )
    lines = [
        "",
        "## 附：海外关注清单（非A股，观察口径）",
        "",
        f"用户长期关注但不在 A 股上市的公司，共 {len(rows)} 家，由 `data/processed/overseas_watchlist_valuation.csv` 渲染（§6.8）。",
        "",
        "- **一律不可买、不构成买入候选**：本清单不入 `a_share_core_valuation_pool.csv`、不进每日量价扫描（§8）、不走买入前闸门（§10），§6.2.1 分层×估值准入矩阵不适用。它只回答「质量几档、该用什么模型、现价贵不贵」。",
        "- 质量分层（§5.7）与策略标签（§6.5）口径与 A 股完全一致，不降低门槛；本清单是用户点名的自选名单而非全市场筛选结果，故层级分布天然偏上，不适用 §5.7.1 的金字塔校准。",
        "- 行序与 A 股主表一致按**质量档 L1→L4**排列，同档内保持 港股→美股→韩股 顺序。",
        "- 档位同样按 §6.2.1.6 现价自动定档（>1.2×带顶=高估；带顶~1.2×带顶=较高估；带内=中性；带底以下按空间≥40% 分低估/较低估），与审定档不同的行显示 `审定档→现档`。带只由证据复核修改。",
        "- 现价/合理价区间/空间均为各自**交易货币**（港股 HKD、美股 USD、韩股 KRW），跨市场不可直接比较；行情同源腾讯快照（`scripts/overseas_quotes.py`）。",
        "- PE 为行情快照 TTM 口径：美股线不提供 PB、韩股线不提供 PE/PB，缺失列显示 —，判档依据见 CSV `fair_price_basis`（多数标的以归一化/中枢利润为锚，表观 PE 不作定档依据）。",
        "",
        "| 市场 | 代码 | 名称 | 质量 | 估值 | 策略 | 现价 | 合理价区间 | 空间 | PE | PB | 估值时间 | 估值事件 |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        *body,
    ]
    return lines, {"changes": changes, "current_tiers": current_tiers}


_RESEARCH_CACHE: dict[str, str] = {}


def _evidence_retrieved(code: str) -> str:
    """证据文件的检索日（§7.4.1 研报触发只能靠新鲜度，不能靠研报发布日比较）。"""
    if code in _RESEARCH_CACHE:
        return _RESEARCH_CACHE[code]
    path = ROOT / f"data/interim/valuation_evidence/{code}.json"
    result = ""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            result = (data.get("retrieved_at_utc") or "")[:10]
        except Exception:                                  # noqa: BLE001
            result = ""
    _RESEARCH_CACHE[code] = result
    return result


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
    as_of: str,
    quotes: dict[str, dict] | None = None,
    forecasts: dict[str, dict[str, str]] | None = None,
    prev_tiers: dict[str, str] | None = None,
    disclosures: dict[str, dict[str, str]] | None = None,
    extra_sections: list[str] | None = None,
) -> dict[str, object]:
    """渲染单一列表阅读版 MD（v1.05）；返回 {'changes': 当日档位变化, 'drift': 现档≠审定档,
    'forecast': 有预告代码, 'forecast_pending': §7.5.5 待复核名单（预告+快报+正式报告，v1.18）,
    'disclosure': 有快报/正式报告代码, 'current_tiers': {code: (name, tier)}}。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    quotes = quotes or {}
    forecasts = forecasts or {}
    prev_tiers = prev_tiers or {}
    # v1.39：阅读版按 **质量档 L1→L3，档内按参考分降序** 排列（§5.7：参考分只作档内排序
    # 展示，不改变矩阵资格、不代为定仓位档）。此前按估值表原序，读者无法一眼看出质量梯度。
    _tier_rank = {tier: index for index, tier in enumerate(("L1", "L2", "L3"))}
    rows = sorted(
        rows,
        key=lambda row: (
            _tier_rank.get(normalize_quality_tier(str(row.get("quality_tier", ""))), 99),
            -(_to_float(row.get("quality_score")) or 0.0),
            str(row.get("security_code", "")),
        ),
    )
    disclosures = disclosures or {}
    quote_line = (
        f"现价更新：{format_quote_time(quotes)}（腾讯行情快照，{len(quotes)}/{len(rows)} 只成功）"
        if quotes
        else "现价未刷新（--quotes skip；现价/空间/档位按估值时点价展示）"
    )
    changes: list[str] = []
    drift: list[str] = []
    forecast_codes: list[str] = []
    disclosure_codes: list[str] = []
    forecast_pending: list[str] = []
    current_tiers: dict[str, tuple[str, str]] = {}

    body: list[str] = []
    for row in rows:
        code = row["security_code"]
        cells = display_cells(row, quotes.get(code))
        frow = forecasts.get(code)
        effective = str(cells["effective_tier"])
        current_tiers[code] = (row["security_name"], effective)
        if effective != str(row.get("valuation_tier", "")):
            drift.append(f"{code}{row['security_name']}")
        prev = prev_tiers.get(code)
        if prev and prev != effective:
            changes.append(f"{code}{row['security_name']} {prev}→{effective}")
        drow = disclosures.get(code)
        if frow:
            forecast_codes.append(code)
        if drow:
            disclosure_codes.append(code)
        if frow or drow:
            # §6.7.8/§6.7.9（v1.16/v1.18）：预告/快报/正式报告公告日晚于 max(估值时间, 估值证据日)
            # = §7.5.5 待复核（缺失回退 pool_as_of）——同晚复核吸收次日戳披露的不再伪欠账。
            reviewed = max(
                str(row.get("valuation_reviewed_at") or row.get("pool_as_of") or ""),
                str(row.get("evidence_available_at") or ""),
            )
            events: list[tuple[str, str]] = []
            if frow and frow.get("notice_date"):
                events.append((str(frow["notice_date"]), "预告"))
            if drow and drow.get("notice_date"):
                events.append((str(drow["notice_date"]), DISCLOSURE_LABELS.get(str(drow.get("disclosure_type")), "披露")))
            latest = max(events) if events else None
            if latest and latest[0] > reviewed:
                forecast_pending.append(f"{code}{row['security_name']}({latest[0]}·{latest[1]})")

        body.append(
            "| {security_code} | {security_name} | {quality_tier_label} | {quality_score} | ".format(**row)
            + str(cells["valuation_cell"])
            + " | {strategy_tag} | ".format(**row)
            + f"{cells['price']} | "
            + f"{cells['band']} | {cells['upside']} | {cells['pe']} | {cells['pb']} | "
            + "{valuation_reviewed_at} | {valuation_evidence_event} |".format(
                valuation_reviewed_at=row.get("valuation_reviewed_at") or "—",
                valuation_evidence_event=row.get("valuation_evidence_event") or "—",
            )
        )

    lines = [
        "# A股核心估值合格池",
        "",
        f"生成日期：{as_of}｜{quote_line}",
        "",
        "本文件由 `scripts/build_a_share_core_valuation_pool.py` 生成，是全量 worth_attention 单一列表阅读版（v1.27 三档分层，v1.05 单一列表）。买入资格由 质量 × 当日档位 按 §6.2.1 矩阵判定；高估/无法估值不可买。",
        "",
        "- **档位按现价自动定档（§6.2.1.6，无人工复核，双向不限幅）**：>1.2×带顶=高估；带顶~1.2×带顶=较高估；带内=中性；带底以下按空间≥40% 分低估/较低估；无法估值不自动定档。与审定档不同的行显示 `审定档→现档`——**箭头左端是审定档（最近一次证据复核的结论），不是昨日档**，可能是多日累计漂移；当日发生的变化另见扫描报告与刷新日志。带本身仍只能由 §7 复核修改（财报/预告/事件）——价格改档、证据改带。",
        "- 现价/PE/PB 为每日扫描时的行情快照（PE 为 TTM 口径）；现价缺失（停牌/请求失败）的行沿用估值时点值。",
        "- 空间 = 区间中值（模型认可的公允中枢）相对现价的涨跌幅，正数代表上行空间、负数代表现价已高于中枢；原带位列与空间重复，已移除（v1.10）。",
        "- 业绩预告不在本表展示（v1.09）：预告物化文件（§6.7.8）只作 §7.5.5 express 复核队列输入，复核完成后其影响体现为 估值时间/估值事件 两列的更新。",
        "- 合理价区间为该股按其策略模型处于「中性」档的价格带，是估值的唯一输出锚（换算依据见池 CSV `fair_price_basis`；模型认可的公允中枢≈区间中值，空间列即按中值/现价计算）。",
        "- 估值时间 = 最近一次估值复核日（合理价区间的推导日）；估值事件 = 该次复核所依据的最新披露（一季报/中报预告/中报/三季报/年报/业绩快报/重大事件）。档位每日按现价自动重算，带只在 §7 复核时更新——「价格改档、证据改带」。审定档、核心理由与复核时点价（`valuation_price`）见池 CSV。",
        *(
            ["- 文末附**海外关注清单**（非A股，§6.8）：只作质量与估值观察，不入本池 CSV、不进每日量价扫描、无买入资格。"]
            if extra_sections
            else []
        ),
        "",
        "| 代码 | 名称 | 质量 | 参考分 | 估值 | 策略 | 现价 | 合理价区间 | 空间 | PE | PB | 估值时间 | 估值事件 |",
        "| --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        *body,
        *(extra_sections or []),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "changes": changes,
        "drift": drift,
        "forecast": forecast_codes,
        "disclosure": disclosure_codes,
        "forecast_pending": forecast_pending,
        "current_tiers": current_tiers,
    }


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
    decision_types = {"excluded": "scan_excluded"}
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
                "decision_type": decision_types.get(row["pool_layer"], "core_valuation_eligible"),
                "decision_result": (
                    f"{row['pool_layer']}({row['valuation_tier']})"
                    if row["pool_layer"] in decision_types
                    else row["valuation_tier"]
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


def log_overseas_decisions(
    log_file: Path,
    rows: list[dict[str, str]],
    as_of: str,
    overseas_file: Path,
    output_md: Path,
) -> None:
    """§6.8 海外关注清单逐票结论日志：decision_type 固定 overseas_watch（不可买，仅观察）。

    只记**当日复核**的行（`valuation_reviewed_at == as_of`），因此每日现价刷新不重复写结论，
    新增或改带的标的在复核当日各留一行。"""
    rows = [row for row in rows if row.get("valuation_reviewed_at") == as_of]
    if not rows:
        return
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    append_decision_log(
        log_file,
        [
            {
                "logged_at_utc": logged_at,
                "workflow_stage": "overseas_watchlist",
                "run_id": f"overseas_watchlist:{as_of}",
                "as_of": as_of,
                "security_code": f"{row.get('market_type', '')}:{row['security_code']}",
                "security_name": row["security_name"],
                "decision_type": "overseas_watch",
                "decision_result": f"{row.get('quality_tier', '')}×{row.get('valuation_tier', '')}（{row.get('strategy_tag', '')}，不可买）",
                "summary_reason": row.get("valuation_reason", ""),
                "input_files": str(overseas_file),
                "source_urls": row.get("evidence_sources", ""),
                "output_file": str(output_md),
                "operator_or_script": "scripts/build_a_share_core_valuation_pool.py",
                "workflow_version": WORKFLOW_VERSION,
            }
            for row in rows
        ],
    )


def _freshness(retrieved: str, as_of: str, label: str) -> str:
    if not retrieved:
        return f"（{label}物化文件缺失，须按 §9.1 步骤 0 抓取）"
    if retrieved < as_of:
        return f"（检索于 {retrieved} ⚠️早于扫描日，数据过期，须按 §9.1 步骤 0 重抓）"
    return f"（检索于 {retrieved}）"


def forecast_summary(flags: dict[str, object], forecast_retrieved: str, as_of: str, disclosure_retrieved: str = "") -> str:
    """§6.7.8/§6.7.9（v1.16/v1.18）刷新汇总的披露部分：预告与快报/正式报告覆盖数 +
    各自检索日（过期加警告）+ §7.5.5 待复核名单本身（并集口径）。"""
    covered = len(list(flags.get("forecast") or []))
    disclosed = len(list(flags.get("disclosure") or []))
    pending = list(flags.get("forecast_pending") or [])
    shown = "、".join(pending[:40]) + (f" …等共 {len(pending)} 只" if len(pending) > 40 else "")
    pending_part = f"；§7.5.5 待复核 {len(pending)} 只（公告日晚于估值时间）" + (f"：{shown}" if pending else "")
    return (
        f"业绩预告覆盖 {covered} 只{_freshness(forecast_retrieved, as_of, '预告')}"
        f"；快报/正式报告覆盖 {disclosed} 只{_freshness(disclosure_retrieved, as_of, '披露')}"
        f"{pending_part}"
    )


def log_price_refresh(
    log_file: Path,
    as_of: str,
    quote_count: int,
    total: int,
    flags: dict[str, object],
    forecast_retrieved: str,
    output_md: Path,
    disclosure_retrieved: str = "",
    overseas_flags: dict[str, object] | None = None,
) -> None:
    """--md-only 现价刷新只写一行汇总日志：当日档位变化 + 披露覆盖与 §7.5.5 待复核名单。"""
    changes = list(flags.get("changes") or [])
    drift = list(flags.get("drift") or [])
    pending = list(flags.get("forecast_pending") or [])
    overseas_changes = list((overseas_flags or {}).get("changes") or [])
    overseas_total = len((overseas_flags or {}).get("current_tiers") or {})
    summary_parts = [
        ("当日档位变化（价格自动定档）：" + "、".join(changes)) if changes else "当日无档位变化",
        f"现档≠审定档共 {len(drift)} 只",
        forecast_summary(flags, forecast_retrieved, as_of, disclosure_retrieved),
    ]
    if overseas_total:
        summary_parts.append(
            f"海外关注清单（§6.8，不可买）{overseas_total} 家，"
            + ("档位变化：" + "、".join(overseas_changes) if overseas_changes else "无档位变化")
        )
    append_decision_log(
        log_file,
        [
            {
                "logged_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "workflow_stage": "core_valuation_pool",
                "run_id": f"pool_price_refresh:{as_of}",
                "as_of": as_of,
                "security_code": "POOL",
                "security_name": "估值池现价刷新",
                "decision_type": "pool_price_refresh",
                "decision_result": (
                    f"quotes {quote_count}/{total}; tier_changes {len(changes)}; drift {len(drift)}; "
                    f"forecast_pending {len(pending)}"
                ),
                "summary_reason": "；".join(summary_parts),
                "input_files": "",
                "source_urls": "https://qt.gtimg.cn/;https://datacenter-web.eastmoney.com/",
                "output_file": str(output_md),
                "operator_or_script": "scripts/build_a_share_core_valuation_pool.py",
                "workflow_version": WORKFLOW_VERSION,
            }
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
    parser.add_argument(
        "--quotes",
        choices=["skip", "fetch"],
        default="skip",
        help="fetch = 拉取腾讯批量行情快照，MD 按现价刷新并自动定档（§6.7.7 每日扫描用）。",
    )
    parser.add_argument(
        "--md-only",
        action="store_true",
        help="只重渲染阅读版 MD（每日现价刷新）：不重写池 CSV，不逐股写池结论日志，只记一行刷新汇总。",
    )
    parser.add_argument(
        "--forecasts",
        type=Path,
        default=DEFAULT_FORECASTS,
        help="业绩预告物化文件（fetch_a_share_earnings_forecasts.py 输出）；缺失时预告列显示 —。",
    )
    parser.add_argument(
        "--disclosures",
        type=Path,
        default=DEFAULT_DISCLOSURES,
        help="定期报告/业绩快报披露物化文件（fetch_a_share_report_disclosures.py 输出，§6.7.9）；缺失时待复核名单仅按预告判定。",
    )
    parser.add_argument(
        "--tier-snapshot",
        type=Path,
        default=DEFAULT_TIER_SNAPSHOT,
        help="当日有效档位快照（用于次日差分出档位变化）。",
    )
    parser.add_argument(
        "--overseas",
        type=Path,
        default=DEFAULT_OVERSEAS,
        help="海外关注清单估值表（§6.8）：渲染为阅读版 MD 附表；缺失时不渲染附表。",
    )
    parser.add_argument(
        "--overseas-tier-snapshot",
        type=Path,
        default=DEFAULT_OVERSEAS_TIER_SNAPSHOT,
        help="海外附表当日有效档位快照（键为 市场:代码）。",
    )
    parser.add_argument("--timeout", type=float, default=8.0, help="行情请求超时（秒）。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_pool(load_csv(args.valuation), load_csv(args.tiers), args.as_of)
    overseas_rows = load_overseas(args.overseas)
    quotes: dict[str, dict] = {}
    overseas_quotes: dict[str, dict] = {}
    if args.quotes == "fetch":
        quotes = fetch_spot_quotes([(row["security_code"], row.get("exchange", "")) for row in rows], timeout=args.timeout)
        overseas_quotes = fetch_overseas_quotes(
            [(row.get("market_type", ""), row["security_code"]) for row in overseas_rows], timeout=args.timeout
        )
    forecasts = load_forecasts(args.forecasts)
    forecast_retrieved = forecasts_retrieved_on(args.forecasts)
    disclosures = load_disclosures(args.disclosures)
    disclosure_retrieved = forecasts_retrieved_on(args.disclosures)
    prev_tiers = load_tier_snapshot(args.tier_snapshot)
    prev_overseas_tiers = load_tier_snapshot(args.overseas_tier_snapshot, pad_code=False)
    fieldnames = [
        "market_type",
        "security_code",
        "security_name",
        "exchange",
        "quality_tier",
        "quality_tier_label",
        "quality_score",
        "pool_layer",
        "matrix_state",
        "band_derivation",
        "band_status",
        "anchor_quality",
        "band_is_floor",
        "cycle_assumption",
        "scenario_band_low",
        "scenario_band_high",
        "upgrade_path",
        "strategy_tag",
        "valuation_tier",
        "valuation_batch_id",
        "valuation_price",
        "total_market_cap_bn",
        "fair_price_low",
        "fair_price_high",
        "fair_price_basis",
        "valuation_pe_ttm",
        "valuation_pb",
        "valuation_reason",
        "valuation_reviewed_at",
        "valuation_evidence_event",
        "valuation_price_as_of",
        "evidence_available_at",
        "pool_as_of",
        "source_file",
    ]
    if not args.md_only:
        write_csv(args.output_csv, rows, fieldnames)
    overseas_section, overseas_flags = build_overseas_section(overseas_rows, overseas_quotes, prev_overseas_tiers)
    flags = write_markdown(
        args.output_md, rows, args.as_of, quotes, forecasts, prev_tiers, disclosures, overseas_section
    )
    write_tier_snapshot(args.tier_snapshot, flags["current_tiers"], args.as_of)  # type: ignore[arg-type]
    if overseas_rows:
        write_tier_snapshot(args.overseas_tier_snapshot, overseas_flags["current_tiers"], args.as_of)  # type: ignore[arg-type]
    changes = list(flags.get("changes") or [])
    overseas_changes = list(overseas_flags.get("changes") or [])
    summary = (
        f"tier changes today: {'、'.join(changes) if changes else '无'}; "
        f"drift vs 审定档: {len(list(flags.get('drift') or []))}; "
        f"{forecast_summary(flags, forecast_retrieved, args.as_of, disclosure_retrieved)}"
        + (
            f"; 海外附表 {len(overseas_rows)} 家（{len(overseas_quotes)} 只取到行情），"
            f"档位变化：{'、'.join(overseas_changes) if overseas_changes else '无'}"
            if overseas_rows
            else ""
        )
    )
    # 海外附表结论只在复核当日入日志（见 log_overseas_decisions），故两种模式都调用。
    log_overseas_decisions(args.log_file, overseas_rows, args.as_of, args.overseas, args.output_md)
    if args.md_only:
        log_price_refresh(
            args.log_file, args.as_of, len(quotes), len(rows), flags, forecast_retrieved,
            args.output_md, disclosure_retrieved, overseas_flags,
        )
        print(f"refreshed {args.output_md} with {len(quotes)}/{len(rows)} quotes; {summary}")
    else:
        log_pool_decisions(args.log_file, rows, args.as_of, args.valuation, args.tiers, args.output_csv, args.output_md)
        print(f"wrote {len(rows)} pool rows to {args.output_csv}; {summary}")


if __name__ == "__main__":
    main()
