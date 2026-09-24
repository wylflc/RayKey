#!/usr/bin/env python3
"""Build the report-driven quality and valuation update queue.

Since v1.18 the valuation-review triggers are keyed on **公告日** (disclosure
notice dates) for all three event families — 业绩预告 (forecasts), 业绩快报
(express reports) and 正式定期报告 (periodic reports) — fed by the two §9.1
step-0 daily fetchers. The legacy period-end comparison (报告期末 vs 复核日,
from the static financial-indicators snapshot) is kept only as a fallback: it
systematically misses any report whose period ended before the last review but
was published after it, which is the normal case in report season once v1.16
forces same-day forecast reviews (判例: 华润三九 7/15 快报 / 大族激光 7/21
快报 invisible until 2026-07-22)."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
from pathlib import Path

from a_share_signal_dates import evidence_iso_for_signal


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTENTION_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"
DEFAULT_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
# OI-094：兜底用的 latest_report_date 缺省读逐季面板目录（随披露增量刷新），
# 不再读已无生产者的 2026-05 指标快照；传文件路径仍按旧快照 CSV 读（复现用）。
DEFAULT_FINANCIALS = ROOT / "data/raw/financials"
DEFAULT_FORECASTS = ROOT / "data/interim/a_share_earnings_forecasts.csv"
DEFAULT_DISCLOSURES = ROOT / "data/interim/a_share_report_disclosures.csv"
DEFAULT_OUTPUT = ROOT / "data/interim/a_share_report_update_queue.csv"
DEFAULT_DOSSIERS = ROOT / "data/processed/a_share_valuation_dossiers.csv"
DEFAULT_MODEL_BANDS = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
# §7.3（OI-209）：档案研究正常化盈利与模型盈利锚（生产带每股 NOPAT × shares_est，ROIC 路径）差距超过 30% 入队，
# 研究数低于模型锚时同时冻结新增买入；复核后任一数较复核时变动超过 10% 且差距仍超过 30% 时重新入队。
RESEARCH_GAP_MAX = 0.30
RESEARCH_RETRIGGER = 0.10
ROIC_PATHS = {"growth", "zero_growth"}


def _num(value) -> float | None:
    try:
        return float(value) if value not in (None, "", "None") else None
    except (TypeError, ValueError):
        return None


def research_nopat_from_parent(parent_yi: float, minority_share: float, nopat_yi: float, net_profit_yi: float) -> float:
    """§6.5.2.2：归母口径的研究数按模型股权桥反解为 NOPAT（亿元）。

    `minority_share` 取生产带同名列（模型分给少数股东的盈利份额），`nopat_yi − net_profit_yi` 取最新年报
    NOPAT 与合并净利之差（税后净利息与金融收益，随资产负债表而非经营盈利变化，按额不按比例）。"""
    return parent_yi / (1.0 - min(max(minority_share, 0.0), 0.95)) + (nopat_yi - net_profit_yi)


def research_divergence(dossier: dict[str, str] | None, band: dict[str, str] | None) -> dict[str, object] | None:
    """研究正常化盈利对模型盈利锚（亿元）；任一侧不可比时返回 None。

    `triggered` = 差距超限且未被复核覆盖（入队）；`freeze` = 入队且研究数低于模型锚（模型较乐观，§7.5 冻结新增买入）。"""
    if not dossier or not band or band.get("roic_path") not in ROIC_PATHS:
        return None
    research = _num(dossier.get("research_nopat_yi"))
    nopat_ps, shares = _num(band.get("nopat_ps")), _num(band.get("shares_est"))
    if not research or research <= 0 or not nopat_ps or not shares or nopat_ps <= 0:
        return None
    model = nopat_ps * shares / 1e8
    gap = max(model, research) / min(model, research) - 1
    exceeds = gap > RESEARCH_GAP_MAX + 1e-9          # 「超过」30%：恰为 30% 不入队，浮点末位不算超过
    triggered = exceeds
    if triggered and dossier.get("divergence_reviewed_at"):
        seen_model = _num(dossier.get("divergence_reviewed_model_yi"))
        seen_research = _num(dossier.get("divergence_reviewed_research_yi"))
        moved = (not seen_model or not seen_research
                 or abs(model / seen_model - 1) > RESEARCH_RETRIGGER
                 or abs(research / seen_research - 1) > RESEARCH_RETRIGGER)
        triggered = moved
    return {"research": research, "model": model, "gap": gap, "exceeds": exceeds, "triggered": triggered,
            "freeze": triggered and research < model}


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_valuation_scope_tier(tier: str) -> bool:
    """§6.1/§7.3（v1.27）：三档全量纳入估值与估值复核范围。"""
    return tier.startswith(("L1", "L2", "L3"))


def _visible(row: dict[str, str], as_of: str) -> bool:
    """公告日晚于证据截止日的行在该时点不可见。
    公告日缺失的行按不可见处理（无法证明其在时点前已披露）。"""
    notice = (row.get("notice_date") or "").strip()[:10]
    return bool(notice) and notice <= as_of


def load_latest_forecasts(rows: list[dict[str, str]], as_of: str) -> dict[str, dict[str, str]]:
    """§7.3（v1.16）：每代码取 `as_of` 时点前公告日最新的预告行（仅 is_latest=T）。
    指标口径（归母/扣非/营收）在此无关——入队只看公告日是否晚于估值时间。"""
    best: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.get("is_latest") != "T" or not _visible(row, as_of):
            continue
        code = row.get("security_code", "").zfill(6)
        current = best.get(code)
        if current is None or row.get("notice_date", "") > current.get("notice_date", ""):
            best[code] = row
    return best


def load_latest_disclosures(rows: list[dict[str, str]], as_of: str) -> dict[str, dict[str, dict[str, str]]]:
    """§7.3（v1.18）：每代码分别取 正式定期报告 与 业绩快报 在 `as_of` 时点前的最新公告行。
    同类型多行取公告日最大者。"""
    best: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        code = row.get("security_code", "").zfill(6)
        dtype = row.get("disclosure_type", "")
        if dtype not in ("periodic_report", "express_report") or not _visible(row, as_of):
            continue
        slot = best.setdefault(code, {})
        current = slot.get(dtype)
        if current is None or row.get("notice_date", "") > current.get("notice_date", ""):
            slot[dtype] = row
    return best


def attention_class(row: dict[str, str] | None) -> str:
    if not row:
        return ""
    raw = (
        row.get("attention_class")
        or row.get("initial_attention_class")
        or row.get("watch_class")
        or row.get("watch_action")
        or ""
    ).strip().lower()
    aliases = {
        "值得关注": "worth_attention",
        "watch": "worth_attention",
        "add": "worth_attention",
        "keep": "worth_attention",
        "临界待定": "boundary_pending",
        "boundary": "boundary_pending",
        "pending": "boundary_pending",
        "垃圾公司": "garbage",
        "garbage_company": "garbage",
        "remove": "garbage",
    }
    return aliases.get(raw, raw)


def build_queue(
    attention_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    valuation_rows: list[dict[str, str]],
    financial_rows: list[dict[str, str]],
    forecast_rows: list[dict[str, str]],
    disclosure_rows: list[dict[str, str]],
    as_of: str,
    dossier_rows: list[dict[str, str]] | None = None,
    band_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    dossiers_by_code = {row["security_code"].zfill(6): row for row in dossier_rows or [] if row.get("security_code")}
    bands_by_code = {row["security_code"].zfill(6): row for row in band_rows or [] if row.get("security_code")}
    attention_by_code = {row["security_code"].zfill(6): row for row in attention_rows if row.get("security_code")}
    financials_by_code = {row["security_code"].zfill(6): row for row in financial_rows if row.get("security_code")}
    valuation_by_code = {row["security_code"].zfill(6): row for row in valuation_rows if row.get("security_code")}
    as_of_date = parse_date(as_of) or datetime.now(timezone.utc).date()
    forecasts_by_code = load_latest_forecasts(forecast_rows, as_of_date.isoformat())
    disclosures_by_code = load_latest_disclosures(disclosure_rows, as_of_date.isoformat())
    output: list[dict[str, object]] = []

    for tier in tier_rows:
        code = tier.get("security_code", "").zfill(6)
        if not code:
            continue
        current_attention_class = attention_class(attention_by_code.get(code))
        if current_attention_class == "garbage":
            continue
        financial = financials_by_code.get(code)
        valuation = valuation_by_code.get(code)
        latest_report_date = parse_date((financial or {}).get("latest_report_date"))
        latest_report_type = (financial or {}).get("latest_report_type", "")
        # v1.18：正式定期报告/快报按公告日触发；报告期以披露物化文件为准刷新静态快照。
        disclosure = disclosures_by_code.get(code, {})
        periodic = disclosure.get("periodic_report")
        express = disclosure.get("express_report")
        periodic_notice_date = parse_date((periodic or {}).get("notice_date"))
        express_notice_date = parse_date((express or {}).get("notice_date"))
        periodic_period = parse_date((periodic or {}).get("report_date"))
        if periodic_period and (latest_report_date is None or periodic_period > latest_report_date):
            latest_report_date = periodic_period
            latest_report_type = (periodic or {}).get("report_label", "") or latest_report_type
        last_quality_review_date = parse_date(tier.get("reviewed_at_utc"))
        # §7.3：估值复核触发以估值结论日为准；缺失时才回退池物化日并标注口径降级。
        valuation_reviewed_raw = (valuation or {}).get("valuation_reviewed_at", "")
        last_valuation_review_date = parse_date(valuation_reviewed_raw)
        valuation_date_basis = "valuation_reviewed_at"
        if last_valuation_review_date is None:
            last_valuation_review_date = parse_date((valuation or {}).get("pool_as_of"))
            valuation_date_basis = "pool_as_of_fallback" if last_valuation_review_date else "no_prior_valuation"
        # v1.18：公告日与 max(估值时间, 估值证据日) 比较——同晚复核吸收了次日戳披露的不再伪欠账
        # （判例：洛阳钼业等 7/10 晚复核已含 7/11 戳预告，仍被名单标记需 7/22 批量确认）。
        last_evidence_date = parse_date((valuation or {}).get("evidence_available_at"))
        review_cutoff = last_valuation_review_date
        if last_evidence_date and (review_cutoff is None or last_evidence_date > review_cutoff):
            review_cutoff = last_evidence_date
        # §7.2（v1.18）：正式报告公告日晚于上次质量复核即触发；报告期末比较仅作披露文件缺失时的回退。
        # v1.26：与 §7.3 同构，改与 max(质量复核日, 质量证据日) 比较——当晚吸收次日戳披露的复核
        # 不再被判伪欠账（判例：宏发股份 7/29 晚复核吸收 7/30 戳中报；东鹏/顺络/乐鑫 7/30 同形态复现）。
        # 分层表未填 evidence_available_at 时自动退化为纯复核日比较，历史行行为不变。
        quality_evidence_date = parse_date(tier.get("evidence_available_at"))
        quality_cutoff = last_quality_review_date
        if quality_evidence_date and (quality_cutoff is None or quality_evidence_date > quality_cutoff):
            quality_cutoff = quality_evidence_date
        quality_review_needed = bool(
            (
                periodic_notice_date
                and (quality_cutoff is None or periodic_notice_date > quality_cutoff)
            )
            or (
                latest_report_date
                and (quality_cutoff is None or latest_report_date > quality_cutoff)
            )
        )
        in_valuation_scope = is_valuation_scope_tier(tier.get("quality_tier", ""))
        # 回退口径（报告期末 vs 复核日）：复核日落在报告期末与披露日之间时会漏触发，仅在披露文件缺失时兜底。
        report_valuation_trigger = bool(
            in_valuation_scope
            and latest_report_date
            and (last_valuation_review_date is None or latest_report_date > last_valuation_review_date)
        )
        # §7.3（v1.16/v1.18）：预告/快报/正式报告公告日晚于估值时间即确定性入队冻结；幅度是复核的结论，不是入队门槛。
        forecast = forecasts_by_code.get(code)
        forecast_notice_date = parse_date((forecast or {}).get("notice_date"))
        forecast_valuation_trigger = bool(
            in_valuation_scope
            and forecast_notice_date
            and (review_cutoff is None or forecast_notice_date > review_cutoff)
        )
        express_valuation_trigger = bool(
            in_valuation_scope
            and express_notice_date
            and (review_cutoff is None or express_notice_date > review_cutoff)
        )
        periodic_valuation_trigger = bool(
            in_valuation_scope
            and periodic_notice_date
            and (review_cutoff is None or periodic_notice_date > review_cutoff)
        )
        divergence = research_divergence(dossiers_by_code.get(code), bands_by_code.get(code)) if in_valuation_scope else None
        divergence_trigger = bool(divergence and divergence["triggered"])
        report_driven_review = (
            report_valuation_trigger
            or forecast_valuation_trigger
            or express_valuation_trigger
            or periodic_valuation_trigger
        )
        valuation_review_needed = report_driven_review or divergence_trigger
        buy_blocked = report_driven_review or bool(divergence and divergence["freeze"])

        event_reasons: list[str] = []
        if quality_review_needed:
            event_reasons.append("latest_report_after_last_quality_review")
        if periodic_valuation_trigger:
            event_reasons.append("report_disclosure_after_last_valuation_review")
        if express_valuation_trigger:
            event_reasons.append("express_report_after_last_valuation_review")
        if forecast_valuation_trigger:
            event_reasons.append("forecast_after_last_valuation_review")
        if report_valuation_trigger and not periodic_valuation_trigger:
            event_reasons.append("latest_report_after_last_valuation_review")
        if divergence_trigger:
            event_reasons.append("research_model_divergence")

        if not event_reasons:
            continue

        if valuation_review_needed:
            update_scope = "quality_and_valuation"
            priority = "high"
        elif quality_review_needed:
            update_scope = "quality_only"
            priority = "medium"
        else:
            update_scope = "none"
            priority = "low"

        output.append(
            {
                "market_type": "A_SHARE",
                "security_code": code,
                "security_name": tier.get("security_name", ""),
                "listed_company_name": tier.get("listed_company_name", ""),
                "exchange": tier.get("exchange", ""),
                "attention_class": current_attention_class,
                "quality_tier": tier.get("quality_tier", ""),
                "quality_tier_label": tier.get("quality_tier_label", ""),
                "strategy_tag": tier.get("primary_strategy_tag", ""),
                "latest_report_date": latest_report_date.isoformat() if latest_report_date else "",
                "latest_report_type": latest_report_type,
                "latest_periodic_notice_date": periodic_notice_date.isoformat() if periodic_notice_date else "",
                "latest_periodic_report_label": (periodic or {}).get("report_label", ""),
                "latest_express_notice_date": express_notice_date.isoformat() if express_notice_date else "",
                "latest_forecast_notice_date": forecast_notice_date.isoformat() if forecast_notice_date else "",
                "latest_forecast_type": (forecast or {}).get("predict_type", ""),
                "last_quality_review_date": last_quality_review_date.isoformat() if last_quality_review_date else "",
                "quality_evidence_available_at": quality_evidence_date.isoformat() if quality_evidence_date else "",
                "quality_date_basis": (
                    "quality_evidence_available_at"
                    if quality_evidence_date and quality_cutoff == quality_evidence_date
                    else "reviewed_at_utc"
                ),
                "last_valuation_review_date": last_valuation_review_date.isoformat() if last_valuation_review_date else "",
                "valuation_date_basis": valuation_date_basis,
                "quality_review_needed": quality_review_needed,
                "valuation_review_needed": valuation_review_needed,
                # §7.5：估值复核未完成前冻结新增买入（研究数高于模型锚的差距复核除外）；每日扫描读取本列执行冻结。
                "buy_blocked": "review_pending" if buy_blocked else "",
                "update_scope": update_scope,
                "queue_priority": priority,
                "queue_reasons": ";".join(event_reasons),
                "research_nopat_yi": f"{divergence['research']:.2f}" if divergence else "",
                "model_nopat_yi": f"{divergence['model']:.2f}" if divergence else "",
                "research_model_gap": f"{divergence['gap']:.4f}" if divergence else "",
                "as_of": as_of_date.isoformat(),
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

    priority_order = {"high": 0, "medium": 1, "low": 2}
    output.sort(key=lambda row: (priority_order.get(str(row["queue_priority"]), 9), row["security_code"]))
    return output


def build_queue_for_signal(
    attention_rows: list[dict[str, str]],
    tier_rows: list[dict[str, str]],
    valuation_rows: list[dict[str, str]],
    financial_rows: list[dict[str, str]],
    forecast_rows: list[dict[str, str]],
    disclosure_rows: list[dict[str, str]],
    signal_date: str,
    dossier_rows: list[dict[str, str]] | None = None,
    band_rows: list[dict[str, str]] | None = None,
) -> list[dict[str, object]]:
    """Production entry: derive the evidence cutoff from one signal date."""
    return build_queue(
        attention_rows,
        tier_rows,
        valuation_rows,
        financial_rows,
        forecast_rows,
        disclosure_rows,
        evidence_iso_for_signal(signal_date),
        dossier_rows,
        band_rows,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="A_SHARE")
    parser.add_argument("--signal-date", required=True, help="信号日；证据日自动取下一工作日")
    parser.add_argument("--attention-triage", type=Path, default=DEFAULT_ATTENTION_TRIAGE)
    parser.add_argument("--tiers", type=Path, default=DEFAULT_TIERS)
    parser.add_argument("--valuation-pool", type=Path, default=DEFAULT_VALUATION_POOL)
    parser.add_argument("--financials", type=Path, default=DEFAULT_FINANCIALS)
    parser.add_argument(
        "--forecasts",
        type=Path,
        default=DEFAULT_FORECASTS,
        help="业绩预告物化文件（§7.1，每日经 §9.1 步骤 0 重抓）；缺失时仅按定期报告触发。",
    )
    parser.add_argument(
        "--report-disclosures",
        type=Path,
        default=DEFAULT_DISCLOSURES,
        help="定期报告/业绩快报披露物化文件（§7.1，每日经 §9.1 步骤 0 重抓）；缺失时退回报告期末比较口径。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dossiers", type=Path, default=DEFAULT_DOSSIERS, help="档案（研究正常化盈利与差距复核记录，§7.3 OI-209）")
    parser.add_argument("--model-bands", type=Path, default=DEFAULT_MODEL_BANDS, help="候选侧生产带（模型盈利锚）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.as_of = evidence_iso_for_signal(args.signal_date)
    if args.market != "A_SHARE":
        raise SystemExit("Only --market A_SHARE is supported.")
    if args.financials.is_dir():
        from quarterly_panel_indicators import load_latest_indicators
        financial_rows = list(load_latest_indicators(args.financials, args.as_of).values())
    else:
        financial_rows = load_csv(args.financials)
    rows = build_queue_for_signal(
        load_csv(args.attention_triage),
        load_csv(args.tiers),
        load_csv(args.valuation_pool),
        financial_rows,
        load_csv(args.forecasts),
        load_csv(args.report_disclosures),
        args.signal_date,
        load_csv(args.dossiers),
        load_csv(args.model_bands),
    )
    fieldnames = [
        "market_type",
        "security_code",
        "security_name",
        "listed_company_name",
        "exchange",
        "attention_class",
        "quality_tier",
        "quality_tier_label",
        "strategy_tag",
        "latest_report_date",
        "latest_report_type",
        "latest_periodic_notice_date",
        "latest_periodic_report_label",
        "latest_express_notice_date",
        "latest_forecast_notice_date",
        "latest_forecast_type",
        "last_quality_review_date",
        "quality_evidence_available_at",
        "quality_date_basis",
        "last_valuation_review_date",
        "valuation_date_basis",
        "quality_review_needed",
        "valuation_review_needed",
        "buy_blocked",
        "update_scope",
        "queue_priority",
        "queue_reasons",
        "research_nopat_yi",
        "model_nopat_yi",
        "research_model_gap",
        "as_of",
        "generated_at_utc",
    ]
    write_csv(args.output, rows, fieldnames)
    from daily_execution_guard import stamp
    stamp(args.output, args.signal_date, (args.forecasts, args.report_disclosures,
                                         args.attention_triage, args.tiers, args.valuation_pool, args.dossiers, args.model_bands))
    forecast_hits = sum(1 for row in rows if "forecast_after_last_valuation_review" in str(row["queue_reasons"]))
    express_hits = sum(1 for row in rows if "express_report_after_last_valuation_review" in str(row["queue_reasons"]))
    periodic_hits = sum(1 for row in rows if "report_disclosure_after_last_valuation_review" in str(row["queue_reasons"]))
    divergence_hits = [str(row["security_name"]) for row in rows if "research_model_divergence" in str(row["queue_reasons"])]
    print(
        f"wrote {len(rows)} rows to {args.output}; "
        f"forecast-triggered {forecast_hits}, express-triggered {express_hits}, periodic-triggered {periodic_hits}, "
        f"research-model divergence {len(divergence_hits)}{('（' + '、'.join(divergence_hits) + '）') if divergence_hits else ''}"
    )


if __name__ == "__main__":
    main()
