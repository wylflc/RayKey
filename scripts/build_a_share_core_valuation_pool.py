#!/usr/bin/env python3
"""Build the A-share core valuation pool.

Materializes ALL worth_attention L1-L3 names into one pool CSV/MD for the
daily scan. The valuation tier is **price-auto-refreshed** (§6.2): the
displayed/effective tier is derived每日 from spot price vs the reviewed fair
band, with no manual review step — tier changes are simply reported in the
daily scan entry. Reviews (§7: reports/预告/events) change the BAND; price
changes the TIER. Tiers are display-only; buy eligibility is §9.3 + §10.1.

This script does not create new valuation opinions: the band, the reviewed
baseline tier (审定档) and reasons come from the valuation table.

Daily refresh: ``--md-only --quotes fetch`` re-renders only the reading MD
(现价/空间/PE/PB + auto tier), diffs effective tiers against the
previous snapshot (`data/interim/pool_effective_tiers.csv`) and logs one
`pool_price_refresh` summary row listing today's tier changes.

The same MD carries the 海外关注清单 appendix (§6.8): non-A-share names the user
tracks, rendered from `overseas_watchlist_valuation.csv` with the identical
§6.2 price-auto-tier logic but kept out of the pool CSV, out of the daily
volume/price scan and out of buy eligibility.

It also carries an L4 dossier archive for user-named A-share companies that
were profiled but did not enter ``worth_attention``. This is a reading-only
lookup section: it preserves the structured attention class and never enters
the pool CSV, production bands, quote refresh, P/V calculation or daily scan.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from a_share_quotes import fetch_spot_quotes
from a_share_signal_dates import evidence_iso_for_signal
from fetch_overseas_earnings_calendar import print_overdue_report
from overseas_quotes import fetch_overseas_quotes
from validate_valuation_bands import check_row as check_band_card
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log
from pv_ratio import load_model_bands, trading_pv  # noqa: E402  v4.62 OI-091
# OI-095：不在 import 时读生产带；main() 按信号日推导的证据日载入（available_at ≤ 证据日），
# 历史日期补跑不得用当日之后才可得的带。
MODEL_BANDS: dict[str, dict] = {}


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
DEFAULT_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/000_a_share_core_valuation_pool.md"
DEFAULT_FORECASTS = ROOT / "data/interim/a_share_earnings_forecasts.csv"
DEFAULT_DISCLOSURES = ROOT / "data/interim/a_share_report_disclosures.csv"
DEFAULT_TIER_SNAPSHOT = ROOT / "data/interim/pool_effective_tiers.csv"
DEFAULT_OVERSEAS = ROOT / "data/processed/overseas_watchlist_valuation.csv"
DEFAULT_OVERSEAS_TIER_SNAPSHOT = ROOT / "data/interim/overseas_effective_tiers.csv"

# 分层档位集合：池只物化 L1-L3（worth_attention 的分层全集）；阅读版另有 L4 档案归档区，
# 但不进入池。§6.2 三态矩阵已退役，矩阵机制随 v4.18 删除（OI-063）。
POOL_TIERS = {"L1", "L2", "L3"}
CORE_LAYER_TIERS = {"L1", "L2"}
VALUATION_ORDER = ["低估", "较低估", "中性", "较高估", "高估"]
# §6.2 价格自动定档阈值（修订先改工作流）。
OVERVALUED_BAND_MULT = 1.2  # 带顶×1.2 以上 = 高估（沿 D 档 100-120% 惯例）
DEEP_UNDERVALUED_UPSIDE = 0.40  # 带底以下且空间（区间中值/现价-1）>= 40% = 低估，否则较低估
# 预告指标口径优先级：归母净利 > 扣非 > 营业收入（§7.1，仅作复核队列输入统计）。
FORECAST_METRIC_PRIORITY = {"004": 0, "005": 1, "006": 2}


def effective_valuation_tier(price: float | None, fair_low: float | None, fair_high: float | None) -> str | None:
    """§6.2 价格自动定档：>1.2×带顶=高估；带顶~1.2×带顶=较高估；带内=中性；
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


def _rel(path: Path) -> str:
    """溯源列写**实际用到的**路径，不写模块默认常量。

    旧版此处硬写 ``DEFAULT_VALUATION``，于是 ``--valuation`` 指向别的文件时，池 CSV 的
    ``source_file`` 仍然记着默认路径——溯源列指向一个本次根本没读过的文件，比留空更糟。
    """
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def normalize_quality_tier(value: str) -> str:
    for tier in ("L1", "L2", "L3"):
        if value.startswith(tier):
            return tier
    return value


def build_pool(
    valuation_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    as_of: str,
    source_file: Path = DEFAULT_VALUATION,
) -> list[dict[str, str]]:
    """物化全量 worth_attention 为单一列表。pool_layer 仅 core（L1/L2）/ tactical（L3）/
    excluded（无法估值）。买入资格只由 §9.3 与 §10.1 决定；三态矩阵列已随 v4.18 删除（OI-063）。"""
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

        if quality_tier not in POOL_TIERS:
            # OI-003：**不得静默跳过**。旧口径遇到无法归入 L1/L2/L3 的行直接 continue，
            # 12 行曾因此消失于池与每日扫描而无任何提示——与「全量 worth_attention 统一扫描」
            # 的意图相反。现改为计数并上报。
            skipped.append(f"{code}{row.get('security_name','')}({quality_tier or '空'})")
            continue

        # §6.7：带必须是模型带（§6.5.1）。blocking（档位反推 / 已退役标签 / 复算不符）→
        # band_status=rebuild_required：校验失败行冻结新增买入（§6.7 末段），修复后再物化。
        # backfill（模型带、仅建带卡未回填）→ 限期登记义务，买入资格不变。
        band_problems, band_severity = check_band_card(row)
        # §6.5.2.4（原 §6.5.5.1 第 3 条）：**「不发卖出」这种状态不再允许存在**。
        # 一条只能回答「便宜」不能回答「贵」的带，不是一条偏保守的带，是一条**没算完的带**；
        # 把它当估值挂在池里、再在卖出侧打补丁，等于用标注掩盖模型缺口。凡带按定义不能
        # 双向使用（下限带／周期假设未决）且**无逐票档案**的，一律判「无法估值」——
        # 可见、随扫、无带即无 P/V 不进买卖判定、不自动定档，并进入 §6.5.2 建档队列。
        undecidable = []
        if str(row.get("band_is_floor", "")).strip().lower() == "true":
            undecidable.append("下限带")
        if row.get("cycle_assumption") == "mean_reversion_assumed":
            undecidable.append("周期假设未决")
        if undecidable and row.get("band_derivation") != "dossier":
            valuation_tier = "无法估值"
            # 带必须一并清空，否则下游（持仓卖出扫描、§6.2 自动定档）会照旧用它
            # 反算档位，「无法估值」就只是个标签而不是状态。原值留在理由里供建档参考。
            ref = f"{row.get('fair_price_low','')}-{row.get('fair_price_high','')}"
            row["valuation_unvaluable_reason"] = (
                "＋".join(undecidable) + f"（§6.5.2 待建档；原口径参考带 {ref}，按定义只能回答便宜、不能回答贵）")
            row["fair_price_low"] = row["fair_price_high"] = ""
        if not band_problems:
            band_status = "ok"
        elif band_severity == "blocking":
            band_status = "rebuild_required"
        else:
            band_status = "backfill_due"
        # 分层决定 core/tactical，与当日估值档无关；仅「无法估值」（含空档）排除。
        if valuation_tier not in VALUATION_ORDER:
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
                "band_derivation": row.get("band_derivation", "") or ("fallback" if band_status == "rebuild_required" else ""),
                "band_status": band_status,
                "anchor_quality": row.get("anchor_quality", ""),
                "band_is_floor": row.get("band_is_floor", ""),
                "valuation_unvaluable_reason": row.get("valuation_unvaluable_reason", ""),
                "anchor_vintage": row.get("anchor_vintage", ""),
                "method_divergence": row.get("method_divergence", ""),
                "runrate_check": row.get("runrate_check", ""),   # 运行率核对结论须可见（§13 第 3 条）
                "cycle_assumption": row.get("cycle_assumption", ""),
                "scenario_band_low": row.get("scenario_band_low", ""),
                "scenario_band_high": row.get("scenario_band_high", ""),
                "upgrade_path": row.get("upgrade_path", ""),
                "strategy_tag": row.get("strategy_tag", ""),
                "valuation_tier": valuation_tier or "（空）",
                "valuation_batch_id": row.get("valuation_batch_id", ""),
                "valuation_price": row.get("current_price", ""),
                # 估值时点总市值（十亿）；扫描按现价比例折算。
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
                "source_file": _rel(source_file),
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
    """预告物化文件的检索日（retrieved_at_utc 最大值折算**北京日期**）；文件缺失返回空。
    §7.1：检索日早于扫描日=数据过期，须按 §9.1 步骤 0 重抓。
    必须折算时区再取日期部：扫描日与 §6.7 的 as-of 都是北京日历日，而戳是 UTC——
    北京 00:00-08:00 之间 UTC 还在前一天，直接取 UTC 日期部会把刚抓的数据误报「过期」
    （判例 2026-08-20 凌晨：v4.27 当晚吸收口径首跑即误报，预告/披露其实是 30 分钟前抓的）。"""
    if not path.exists():
        return ""
    stamps = [str(row.get("retrieved_at_utc") or "") for row in load_csv(path)]
    if not stamps:
        return ""
    latest = max(stamps)
    try:
        dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.astimezone(timezone(timedelta(hours=8)))).date().isoformat()
    except ValueError:
        return latest[:10]


DISCLOSURE_LABELS = {"periodic_report": "定期报告", "express_report": "快报"}


def load_disclosures(path: Path) -> dict[str, dict[str, str]]:
    """§7.1：每代码取 正式定期报告/业绩快报 中公告日最新的一行，
    供 §7.5.1 待复核名单判定（与预告公告日取并集后的最大者比较估值时间）。"""
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
    """阅读版单元格：现价/空间/PE/PB 按行情快照刷新，档位按 §6.2 价格自动定档。"""
    low = _to_float(row.get("fair_price_low"))
    high = _to_float(row.get("fair_price_high"))
    val_price = _to_float(row.get("valuation_price"))
    spot = _to_float(quote.get("price")) if quote else None
    ref_price = spot if spot else val_price

    # v1.47：判不了的行已在物化阶段改判「无法估值」，阅读版不再出现「高估但不发卖出」
    # 这类自相矛盾的格子，故 `（下限）`/`·不发卖出` 两个标记一并删除。留下的每一条带
    # 都是可双向使用的带。
    #
    # v2.03：`（档）` 标记删除。它原本区分「逐票档案带 vs 通用模型带」，但 v2.00 起
    # 全池已全部建档，且未建档的一律判「无法估值」并清空带——即「带非空 ⇔ 档案带」
    # 恒成立，标记出现在 100% 的行上，不再区分任何东西（§13 第 3 条：恒真的标注
    # 与恒亮的告警同型，都是没有信息量的噪声）。带的来源改由表头一句话统一说明。
    unvaluable = str(row.get("valuation_tier", "")) == "无法估值"
    if low is None or high is None or unvaluable:
        band = "—"
    else:
        band = row["fair_price_low"] if row["fair_price_low"] == row["fair_price_high"] else f"{row['fair_price_low']}-{row['fair_price_high']}"

    if low is None or high is None or not ref_price or unvaluable:
        upside = "—"
    else:
        pct = round(((low + high) / 2 / ref_price - 1) * 100)
        upside = "0%" if pct == 0 else f"{pct:+d}%"
    # 2026-08-23 用户指令：阅读版改列**合理估值 V**（= 区间中值 = 模型内在价值）与 **P/V**（§3 定义：ROIC 路径为
    # (现价+每股净负债)÷每股企业价值、其余 现价÷V，与 §9.3 同一口径、三位小数），合理价区间／空间两列移出阅读版（仍在 CSV；定档仍按带与空间，§6.2）。
    mid = (low + high) / 2 if (low is not None and high is not None and not unvaluable) else None
    fair_value = f"{mid:.2f}" if mid else "—"
    # v4.62（OI-091）：P/V 按 `pv_ratio.trading_pv`（ROIC 路径 (现价+净负债)÷EV），生产带行缺失时退回 现价÷V
    pv_val = None
    if mid and ref_price:
        band_row = MODEL_BANDS.get(str(row.get("security_code", "")).zfill(6))
        pv_val = trading_pv(ref_price, band_row) if band_row else None
        if pv_val is None:
            pv_val = ref_price / mid
    pv = f"{pv_val:.3f}" if pv_val is not None else "—"

    stored = str(row.get("valuation_tier", ""))
    # 无法估值无可靠带，不自动定档（§6.2）；其余按现价（缺失时按估值价）定档。
    effective = stored if stored == "无法估值" else (effective_valuation_tier(ref_price, low, high) or stored)

    spot_pe = _to_float(quote.get("pe_ttm")) if quote else None
    spot_pb = _to_float(quote.get("pb")) if quote else None
    cell = effective if effective == stored else f"{stored}→{effective}"
    return {
        "price": f"{spot:.2f}" if spot else "—",
        "band": band,
        "upside": upside,
        "fair_value": fair_value,
        "fair_value_num": mid,
        "pv": pv,
        "pe": f"{spot_pe:.2f}" if spot_pe else str(row.get("valuation_pe_ttm") or "—"),
        "pb": f"{spot_pb:.2f}" if spot_pb else str(row.get("valuation_pb") or "—"),
        "effective_tier": effective,
        "valuation_cell": cell,
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


def _display_valuation_path(method: str) -> str:
    """阅读版只显示方法名，不展示实现章节或口径注记。"""
    if not method:
        return "—"
    return method.split("（", 1)[0].split("：", 1)[0]


def build_l4_dossier_section(
    dossier_rows: list[dict[str, str]],
    triage_rows: list[dict[str, str]],
) -> tuple[list[str], int]:
    """渲染用户点名建档但未入关注池的 L4 阅读归档区。

    筛选依据只认逐票档案 ``notes`` 中的「用户点名建档」来源和三类表当前状态；
    不从目录存在性猜测，避免把全市场批量建档误列为用户点名。L4 是本文档归档层级，
    ``attention_class`` 原样展示，不触碰质量真值或买入资格。
    """
    triage_by_code = {
        str(row.get("security_code", "")).zfill(6): row for row in triage_rows
    }
    selected: list[tuple[dict[str, str], str]] = []
    for row in dossier_rows:
        code = str(row.get("security_code", "")).zfill(6)
        triage = triage_by_code.get(code)
        if not triage or triage.get("attention_class") == "worth_attention":
            continue
        if "用户点名建档" not in str(row.get("notes", "")):
            continue
        selected.append((row, str(triage.get("attention_class") or "—")))

    if not selected:
        return [], 0
    selected.sort(key=lambda item: str(item[0].get("security_code", "")).zfill(6))

    body: list[str] = []
    for row, attention_class in selected:
        code = str(row.get("security_code", "")).zfill(6)
        name = str(row.get("security_name") or code)
        low, high = _to_float(row.get("band_low")), _to_float(row.get("band_high"))
        if low is None or high is None or low <= 0 or high <= 0:
            band, fair_value, method = "—", "—", "无法估值"
        else:
            band = f"{low:.2f}" if low == high else f"{low:.2f}-{high:.2f}"
            fair_value = f"{(low + high) / 2:.2f}"
            method = _display_valuation_path(str(row.get("band_method") or "")) or "—"
        dossier_dir = Path(str(row.get("dossier_dir") or f"data/companies/{code}_{name}"))
        dossier_link = f"../companies/{dossier_dir.name}/README.md"
        body.append(
            f"| {code} | [{name}]({dossier_link}) | L4 | {attention_class} | "
            f"{band} | {fair_value} | {method} | {row.get('reviewed_at') or '—'} |"
        )

    lines = [
        "",
        "## L4｜已建档但未进入关注池",
        "",
        f"共 {len(selected)} 家。L4 为本阅读版的档案归档层级；`名单状态` 保留结构化 `attention_class`。",
        "",
        "- 仅维护逐票档案与合理价；不进入核心池 CSV、生产带、每日行情、`P/V`、每日扫描或 §9.3。",
        "- 合理价区间与中值 `V` 取逐票估值档案；无法估值显示 —。公司名称可直接打开档案。",
        "",
        "| 代码 | 名称/档案 | 归档层级 | 名单状态 | 合理价区间 | 合理估值 V | 估值方法 | 档案更新 |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
        *body,
    ]
    return lines, len(selected)


def build_overseas_section(
    rows: list[dict[str, str]],
    quotes: dict[str, dict] | None = None,
    prev_tiers: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, object]]:
    """渲染 §6.8 海外关注清单附表：档位仍按 §6.2 现价自动定档，但不入池 CSV、
    不入每日量价扫描、无买入资格。返回 (MD 行, {'changes', 'current_tiers'})。"""
    if not rows:
        return [], {"changes": [], "current_tiers": {}}
    quotes = quotes or {}
    prev_tiers = prev_tiers or {}
    changes: list[str] = []
    current_tiers: dict[str, tuple[str, str]] = {}
    body: list[str] = []
    # 与 A 股主表一致按质量档 L1→L4 排序（A 股池无 L4 行，海外清单有）。
    tier_rank = {tier: index for index, tier in enumerate(("L1", "L2", "L3", "L4"))}
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
        ref_price = spot if spot else _to_float(row.get("valuation_price"))
        price_cell = _fmt_number(ref_price, currency)
        low, high = _to_float(row.get("fair_price_low")), _to_float(row.get("fair_price_high"))
        unvaluable = str(row.get("valuation_tier", "")) == "无法估值"
        mid = (low + high) / 2 if (low is not None and high is not None and not unvaluable) else None
        fair_cell = _fmt_number(mid, currency) if mid else "—"
        pv_cell = f"{ref_price / mid:.3f}" if (mid and ref_price) else "—"
        method = str(row.get("band_method") or row.get("valuation_method") or "")
        path_cell = _display_valuation_path(method)
        body.append(
            # 参考分（§5.7.4）与 A 股主表同列位：质量档之后、估值档之前。海外清单
            # 2026-08-03 起逐票打分，此前该列不存在（附表只有质量档、无档内序位）。
            # 市场 / 代码 两列于 2026-08-06 按用户指令删除（§6.8 第 4 条）；两者仍在
            # CSV 里，只是不进阅读版。`market`/`code` 仍用于行情键与档位快照键。
            "| {name} | {tier} | {score} | ".format(
                name=row["security_name"],
                tier=row.get("quality_tier", "—"),
                score=row.get("quality_score") or "—",
            )
            + f"{cells['valuation_cell']} | {path_cell} | "
            + f"{price_cell} | {fair_cell} | {pv_cell} | "
            + f"{row.get('valuation_reviewed_at') or '—'} | {row.get('valuation_evidence_event') or '—'} |"
        )
    lines = [
        "",
        "## 附：海外关注清单（非A股，观察口径）",
        "",
        f"共 {len(rows)} 家，仅供观察，不进入 A 股候选池，也不具备买入资格。",
        "",
        "- 现价与合理估值按各自交易货币显示；`P/V` 无量纲。参考分只用于同档排序。",
        "- 合理估值取当前估值档案；无法估值行显示 —。估值时间与事件取最新正式报告的公开可得日和报告类型。",
        "",
        "| 名称 | 质量 | 参考分 | 估值 | 估值路径 | 现价 | 合理估值 | P/V | 估值时间 | 估值事件 |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
        *body,
    ]
    return lines, {"changes": changes, "current_tiers": current_tiers}


def load_valuation_paths() -> dict[str, str]:
    """池模型带文件（v4.00 ROIC 口径）的 `roic_path` → 「估值路径」展示列。

    取代原「策略」列（通用十一类标签，v4.00 起不再展示——它既不参与带计算也不参与买卖，
    对读者的问题「这条带是怎么来的」没有回答；估值路径回答的正是这个）。
    """
    path = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
    label = {"growth": "ROIC·增长", "zero_growth": "ROIC·零增长",
             "equity_fallback": "权益退路", "bank_divspread": "银行/保险·股利折现"}
    out: dict[str, str] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                code = (row.get("security_code") or "").zfill(6)
                out[code] = label.get((row.get("roic_path") or "").strip(), "权益退路")
    return out


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
    as_of: str,
    quotes: dict[str, dict] | None = None,
    forecasts: dict[str, dict[str, str]] | None = None,
    prev_tiers: dict[str, str] | None = None,
    disclosures: dict[str, dict[str, str]] | None = None,
    extra_sections: list[str] | None = None,
    l4_count: int = 0,
    overseas_count: int = 0,
) -> dict[str, object]:
    """渲染单一列表阅读版 MD（v1.05）；返回 {'changes': 当日档位变化, 'drift': 现档≠审定档,
    'forecast': 有预告代码, 'forecast_pending': §7.5.1 待复核名单（预告+快报+正式报告，v1.18）,
    'disclosure': 有快报/正式报告代码, 'current_tiers': {code: (name, tier)}}。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    quotes = quotes or {}
    forecasts = forecasts or {}
    prev_tiers = prev_tiers or {}
    valuation_paths = load_valuation_paths()
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
        else "现价未刷新（--quotes skip；现价/P/V/档位按估值时点价展示）"
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
            # §7.1/§7.3：预告/快报/正式报告公告日晚于 max(估值时间, 估值证据日)
            # = §7.5.1 待复核（缺失回退 pool_as_of）——同晚复核吸收次日戳披露的不再伪欠账。
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
            + f" | {valuation_paths.get(str(row.get('security_code', '')).zfill(6), '手工带')} | "
            + f"{cells['price']} | "
            + f"{cells['fair_value']} | {cells['pv']} | "
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
        "本表为全量 `worth_attention` 阅读版；估值档仅作展示，买卖以工作流 §9.3 为准。",
        "",
        "- 合理估值为合理价区间中值；`P/V` = 现价 ÷ 合理估值。估值路径只显示当前方法名。",
        "- 现价取每日行情快照，缺失时沿用估值时点值；档位随现价更新，合理价带随证据复核更新。",
        "- 估值时间为本次估值所依据证据的公开可得日；估值事件为对应报告或重大事件。",
        *(
            ["- L4 归档区仅供查找已建档但未入关注池的公司，不取每日行情、不进入扫描。"]
            if l4_count
            else []
        ),
        *(
            ["- 文末海外关注清单仅供观察，不进入 A 股候选池，也不具备买入资格。"]
            if overseas_count
            else []
        ),
        "",
        "| 代码 | 名称 | 质量 | 参考分 | 估值 | 估值路径 | 现价 | 合理估值 | P/V | 估值时间 | 估值事件 |",
        "| --- | --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- |",
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

    OI-102 起海外 `valuation_reviewed_at` 存**财报证据日**，不能再拿它判断脚本在哪天完成复核。
    只记录估值脚本写下的本批 `valuation_batch_id`，因此每日现价刷新不会重复写结论。"""
    batch_id = f"overseas_review_{as_of.replace('-', '')}"
    rows = [row for row in rows if row.get("valuation_batch_id") == batch_id]
    if log_file.exists():
        with log_file.open(encoding="utf-8-sig", newline="") as handle:
            logged = {row.get("security_code", "") for row in csv.DictReader(handle)
                      if row.get("run_id") == f"overseas_watchlist:{as_of}"}
        rows = [row for row in rows if f"{row.get('market_type', '')}:{row['security_code']}" not in logged]
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
    """§7.1/§7.3刷新汇总的披露部分：预告与快报/正式报告覆盖数 +
    各自检索日（过期加警告）+ §7.5.1 待复核名单本身（并集口径）。"""
    covered = len(list(flags.get("forecast") or []))
    disclosed = len(list(flags.get("disclosure") or []))
    pending = list(flags.get("forecast_pending") or [])
    shown = "、".join(pending[:40]) + (f" …等共 {len(pending)} 只" if len(pending) > 40 else "")
    pending_part = f"；§7.5.1 待复核 {len(pending)} 只（公告日晚于估值时间）" + (f"：{shown}" if pending else "")
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
    input_files: str = "",
) -> None:
    """--md-only 现价刷新只写一行汇总日志：当日档位变化 + 披露覆盖与 §7.5.1 待复核名单。"""
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
                "input_files": input_files,
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
    parser.add_argument("--dossiers", type=Path, default=DEFAULT_DOSSIERS)
    parser.add_argument("--attention-triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    parser.add_argument(
        "--quotes",
        choices=["skip", "fetch"],
        default="fetch",
        # **缺省 fetch（2026-08-17 改）**：阅读版的现价/空间/档位三列都依赖行情快照，
        # 缺省 skip 时它们**静默退回估值时点值**、现价整列显示「—」，而六步链一路不带该参数——
        # 用户 2026-08-17 反馈「股价列很多都是空」即由此而来。取数失败仍会优雅降级为「未刷新」。
        help="fetch（缺省）= 拉取腾讯批量行情快照，MD 按现价刷新并自动定档；skip = 离线渲染，现价列显示 —。",
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
        help="定期报告/业绩快报披露物化文件（fetch_a_share_report_disclosures.py 输出，§7.1）；缺失时待复核名单仅按预告判定。",
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
    global MODEL_BANDS
    args = parse_args()
    args.as_of = args.signal_date
    args.evidence_date = evidence_iso_for_signal(args.signal_date)
    MODEL_BANDS = load_model_bands(as_of=args.evidence_date)
    rows = build_pool(load_csv(args.valuation), load_csv(args.tiers), args.as_of, args.valuation)
    dossier_rows = load_csv(args.dossiers) if args.dossiers.exists() else []
    triage_rows = load_csv(args.attention_triage) if args.attention_triage.exists() else []
    l4_section, l4_count = build_l4_dossier_section(dossier_rows, triage_rows)
    overseas_rows = load_overseas(args.overseas)
    # §6.8 复核触发① 的落地校验（OI-039）：财报已披露而带还建在披露前的证据上，当天就喊出来。
    # 放在这里是因为本脚本是 §9.1 第二步**每日必跑**的那一个，而海外行不进 §9.1 1a 的机械覆盖；
    # 检查只读清单里已存的日期列，不联网，故不增加每日跑批的耗时。日期源由
    # `fetch_overseas_earnings_calendar.py` 定期刷新。
    if overseas_rows:
        try:
            print_overdue_report(overseas_rows, date.fromisoformat(args.as_of))
        except ValueError:
            print("  §6.8 复核触发① 自检跳过：信号日非合法日期")
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
        "band_derivation",
        "band_status",
        "anchor_quality",
        "band_is_floor",
        "valuation_unvaluable_reason",
        "anchor_vintage",
        "method_divergence",
        "runrate_check",
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
        args.output_md, rows, args.as_of, quotes, forecasts, prev_tiers, disclosures,
        [*l4_section, *overseas_section], l4_count, len(overseas_rows),
    )
    write_tier_snapshot(args.tier_snapshot, flags["current_tiers"], args.as_of)  # type: ignore[arg-type]
    if overseas_rows:
        write_tier_snapshot(args.overseas_tier_snapshot, overseas_flags["current_tiers"], args.as_of)  # type: ignore[arg-type]
    changes = list(flags.get("changes") or [])
    overseas_changes = list(overseas_flags.get("changes") or [])
    summary = (
        f"tier changes today: {'、'.join(changes) if changes else '无'}; "
        f"drift vs 审定档: {len(list(flags.get('drift') or []))}; "
        f"{forecast_summary(flags, forecast_retrieved, args.as_of, disclosure_retrieved)}; "
        f"L4 档案区 {l4_count} 家"
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
            # 溯源：旧版此处写空串，刷新行看不出读了哪些文件（§13 第 3 条同型）。
            input_files=";".join(_rel(p) for p in (
                args.valuation, args.tiers, args.dossiers, args.attention_triage,
                args.tier_snapshot, args.forecasts, args.disclosures
            )),
        )
        print(f"refreshed {args.output_md} with {len(quotes)}/{len(rows)} quotes; {summary}")
    else:
        log_pool_decisions(args.log_file, rows, args.as_of, args.valuation, args.tiers, args.output_csv, args.output_md)
        print(f"wrote {len(rows)} pool rows to {args.output_csv}; {summary}")


if __name__ == "__main__":
    main()
