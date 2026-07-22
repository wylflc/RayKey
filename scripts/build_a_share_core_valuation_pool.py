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
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path

from a_share_quotes import fetch_spot_quotes
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VALUATION = ROOT / "data/processed/a_share_focus_watchlist_l1_l2_valuation.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/000_a_share_core_valuation_pool.md"
DEFAULT_FORECASTS = ROOT / "data/interim/a_share_earnings_forecasts.csv"
DEFAULT_DISCLOSURES = ROOT / "data/interim/a_share_report_disclosures.csv"
DEFAULT_TIER_SNAPSHOT = ROOT / "data/interim/pool_effective_tiers.csv"

# §6.2.1 分层×估值准入矩阵：层级越低，买入估值门槛越严。
TIER_ELIGIBLE_VALUATIONS = {
    "L1": {"低估", "较低估", "中性", "较高估"},
    "L2": {"低估", "较低估", "中性"},
    "L3": {"低估", "较低估"},
    "L4": {"低估"},
}
CORE_LAYER_TIERS = {"L1", "L2"}
WATCH_VALUATIONS = {"低估", "较低估", "中性", "较高估"}
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
    for tier in ("L1", "L2", "L3", "L4", "L5"):
        if value.startswith(tier):
            return tier
    return value


def build_pool(
    valuation_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    as_of: str,
) -> list[dict[str, str]]:
    """物化 L1-L4 全量为单一列表（v1.05）。pool_layer 为审定档口径的物化标注：
    core/tactical（过矩阵）、watch_only（非高估未过矩阵）、excluded（高估/无法估值）；
    每日买入资格以扫描时的价格自动定档为准，pool_layer 仅作审计口径。"""
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
            pool_layer = "excluded"

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


def load_tier_snapshot(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {row["security_code"].zfill(6): row.get("effective_tier", "") for row in load_csv(path)}


def write_tier_snapshot(path: Path, tiers: dict[str, tuple[str, str]], as_of: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["security_code", "security_name", "effective_tier", "as_of"])
        writer.writeheader()
        for code, (name, tier) in sorted(tiers.items()):
            writer.writerow({"security_code": code, "security_name": name, "effective_tier": tier, "as_of": as_of})


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
    as_of: str,
    quotes: dict[str, dict] | None = None,
    forecasts: dict[str, dict[str, str]] | None = None,
    prev_tiers: dict[str, str] | None = None,
    disclosures: dict[str, dict[str, str]] | None = None,
) -> dict[str, object]:
    """渲染单一列表阅读版 MD（v1.05）；返回 {'changes': 当日档位变化, 'drift': 现档≠审定档,
    'forecast': 有预告代码, 'forecast_pending': §7.5.5 待复核名单（预告+快报+正式报告，v1.18）,
    'disclosure': 有快报/正式报告代码, 'current_tiers': {code: (name, tier)}}。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    quotes = quotes or {}
    forecasts = forecasts or {}
    prev_tiers = prev_tiers or {}
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
            "| {security_code} | {security_name} | {quality_tier_label} | ".format(**row)
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
        "本文件由 `scripts/build_a_share_core_valuation_pool.py` 生成，是 L1-L4 全量 worth_attention 单一列表阅读版（v1.05）。买入资格由 质量 × 当日档位 按 §6.2.1 矩阵判定；高估/无法估值不可买。",
        "",
        "- **档位按现价自动定档（§6.2.1.6，无人工复核，双向不限幅）**：>1.2×带顶=高估；带顶~1.2×带顶=较高估；带内=中性；带底以下按空间≥40% 分低估/较低估；无法估值不自动定档。与审定档不同的行显示 `审定档→现档`——**箭头左端是审定档（最近一次证据复核的结论），不是昨日档**，可能是多日累计漂移；当日发生的变化另见扫描报告与刷新日志。带本身仍只能由 §7 复核修改（财报/预告/事件）——价格改档、证据改带。",
        "- 现价/PE/PB 为每日扫描时的行情快照（PE 为 TTM 口径）；现价缺失（停牌/请求失败）的行沿用估值时点值。",
        "- 空间 = 区间中值（模型认可的公允中枢）相对现价的涨跌幅，正数代表上行空间、负数代表现价已高于中枢；原带位列与空间重复，已移除（v1.10）。",
        "- 业绩预告不在本表展示（v1.09）：预告物化文件（§6.7.8）只作 §7.5.5 express 复核队列输入，复核完成后其影响体现为 估值时间/估值事件 两列的更新。",
        "- 合理价区间为该股按其策略模型处于「中性」档的价格带，是估值的唯一输出锚（换算依据见池 CSV `fair_price_basis`；模型认可的公允中枢≈区间中值，空间列即按中值/现价计算）。",
        "- 估值时间 = 最近一次估值复核日（合理价区间的推导日）；估值事件 = 该次复核所依据的最新披露（一季报/中报预告/中报/三季报/年报/业绩快报/重大事件）。档位每日按现价自动重算，带只在 §7 复核时更新——「价格改档、证据改带」。审定档、核心理由与复核时点价（`valuation_price`）见池 CSV。",
        "",
        "| 代码 | 名称 | 质量 | 估值 | 策略 | 现价 | 合理价区间 | 空间 | PE | PB | 估值时间 | 估值事件 |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        *body,
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
    decision_types = {"watch_only": "scan_watch_only", "excluded": "scan_excluded"}
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
) -> None:
    """--md-only 现价刷新只写一行汇总日志：当日档位变化 + 披露覆盖与 §7.5.5 待复核名单。"""
    changes = list(flags.get("changes") or [])
    drift = list(flags.get("drift") or [])
    pending = list(flags.get("forecast_pending") or [])
    summary_parts = [
        ("当日档位变化（价格自动定档）：" + "、".join(changes)) if changes else "当日无档位变化",
        f"现档≠审定档共 {len(drift)} 只",
        forecast_summary(flags, forecast_retrieved, as_of, disclosure_retrieved),
    ]
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
    parser.add_argument("--timeout", type=float, default=8.0, help="行情请求超时（秒）。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = build_pool(load_csv(args.valuation), load_csv(args.tiers), args.as_of)
    quotes: dict[str, dict] = {}
    if args.quotes == "fetch":
        quotes = fetch_spot_quotes([(row["security_code"], row.get("exchange", "")) for row in rows], timeout=args.timeout)
    forecasts = load_forecasts(args.forecasts)
    forecast_retrieved = forecasts_retrieved_on(args.forecasts)
    disclosures = load_disclosures(args.disclosures)
    disclosure_retrieved = forecasts_retrieved_on(args.disclosures)
    prev_tiers = load_tier_snapshot(args.tier_snapshot)
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
    flags = write_markdown(args.output_md, rows, args.as_of, quotes, forecasts, prev_tiers, disclosures)
    write_tier_snapshot(args.tier_snapshot, flags["current_tiers"], args.as_of)  # type: ignore[arg-type]
    changes = list(flags.get("changes") or [])
    summary = (
        f"tier changes today: {'、'.join(changes) if changes else '无'}; "
        f"drift vs 审定档: {len(list(flags.get('drift') or []))}; "
        f"{forecast_summary(flags, forecast_retrieved, args.as_of, disclosure_retrieved)}"
    )
    if args.md_only:
        log_price_refresh(args.log_file, args.as_of, len(quotes), len(rows), flags, forecast_retrieved, args.output_md, disclosure_retrieved)
        print(f"refreshed {args.output_md} with {len(quotes)}/{len(rows)} quotes; {summary}")
    else:
        log_pool_decisions(args.log_file, rows, args.as_of, args.valuation, args.tiers, args.output_csv, args.output_md)
        print(f"wrote {len(rows)} pool rows to {args.output_csv}; {summary}")


if __name__ == "__main__":
    main()
