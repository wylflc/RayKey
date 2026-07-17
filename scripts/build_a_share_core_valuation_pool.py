#!/usr/bin/env python3
"""Build the A-share core valuation pool.

The pool is the formal input for daily volume-price screening. A security is
eligible only when it is both:

1. an L1/L2 quality company; and
2. not marked as overvalued or impossible to value in the valuation pass.

This script intentionally does not create new valuation opinions. It only
materializes the latest reviewed valuation table into the workflow input.

Daily price refresh (§6.7/§6.2.1.6, v1.03): with ``--md-only --quotes fetch``
the script re-renders only the reading MD with a spot-quote column set
(现价/带位/空间/PE/PB) and flags rows whose price broke above the fair band
top (估值列 ``*``，待 §7.4.7 express 复核), without rewriting the pool CSV or
re-logging per-row pool decisions.
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

# §6.2.1 分层×估值准入矩阵：层级越低，买入估值门槛越严。
TIER_ELIGIBLE_VALUATIONS = {
    "L1": {"低估", "较低估", "中性", "可接受较高估"},
    "L2": {"低估", "较低估", "中性"},
    "L3": {"低估", "较低估"},
    "L4": {"低估"},
}
CORE_LAYER_TIERS = {"L1", "L2"}
# v20 §6.7.5：未过准入矩阵但估值非高估/非无法估值的 L1-L4 → watch_only 仅观察层。
WATCH_VALUATIONS = {"低估", "较低估", "中性", "可接受较高估"}
# §6.2.1.6 价格刷新：现价升破带顶时打 * 的存档档位（可接受较高估/高估本就在带顶之上，不重复标）。
BAND_TOP_FLAG_TIERS = {"低估", "较低估", "中性"}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """返回 (池行 core/tactical/watch_only, 排除行 高估/无法估值)。排除行只用于阅读版列示。"""
    tier_by_code = {row["security_code"].zfill(6): row for row in tier_rows}
    output: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []

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
            excluded.append(
                {
                    "security_code": code,
                    "security_name": row.get("security_name", ""),
                    "exchange": infer_exchange(code, tier_row),
                    "quality_tier_label": row.get("quality_tier") or (tier_row or {}).get("quality_tier_label", ""),
                    "valuation_tier": valuation_tier or "（空）",
                    "valuation_price": row.get("current_price", ""),
                    "fair_price_low": row.get("fair_price_low", ""),
                    "fair_price_high": row.get("fair_price_high", ""),
                    "fair_price_basis": row.get("fair_price_basis", ""),
                    "valuation_pe_ttm": row.get("pe_ttm", ""),
                    "valuation_pb": row.get("pb", ""),
                    "valuation_reason": row.get("valuation_reason", ""),
                }
            )
            continue

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
                "valuation_tier": valuation_tier,
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
                "valuation_price_as_of": row.get("valuation_price_as_of", ""),
                "evidence_available_at": row.get("evidence_available_at", ""),
                "pool_as_of": as_of,
                "source_file": str(DEFAULT_VALUATION.relative_to(ROOT)),
            }
        )

    return output, excluded


def _to_float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result


def display_cells(row: dict[str, str], quote: dict | None) -> dict[str, str | bool]:
    """阅读版单元格：现价/带位/空间/PE/PB 按行情快照刷新；无快照行沿用估值时点值。"""
    low = _to_float(row.get("fair_price_low"))
    high = _to_float(row.get("fair_price_high"))
    val_price = _to_float(row.get("valuation_price"))
    spot = _to_float(quote.get("price")) if quote else None
    ref_price = spot if spot else val_price

    if low is None or high is None:
        band = "—"
    else:
        band = row["fair_price_low"] if row["fair_price_low"] == row["fair_price_high"] else f"{row['fair_price_low']}-{row['fair_price_high']}"

    above_top = False
    if low is None or high is None or not ref_price:
        band_pos = "—"
    elif ref_price > high:
        band_pos = f"↑+{(ref_price / high - 1) * 100:.0f}%"
        above_top = True
    elif ref_price < low:
        band_pos = f"↓-{(1 - ref_price / low) * 100:.0f}%"
    else:
        band_pos = f"{(ref_price - low) / (high - low) * 100:.0f}%" if high > low else "0%"

    if low is None or high is None or not ref_price:
        upside = "—"
    else:
        pct = round(((low + high) / 2 / ref_price - 1) * 100)
        upside = "0%" if pct == 0 else f"{pct:+d}%"

    spot_pe = _to_float(quote.get("pe_ttm")) if quote else None
    spot_pb = _to_float(quote.get("pb")) if quote else None
    flagged = above_top and row.get("valuation_tier", "") in BAND_TOP_FLAG_TIERS
    return {
        "price": f"{spot:.2f}" if spot else "—",
        "band": band,
        "band_pos": band_pos,
        "upside": upside,
        "pe": f"{spot_pe:.2f}" if spot_pe else str(row.get("valuation_pe_ttm") or "—"),
        "pb": f"{spot_pb:.2f}" if spot_pb else str(row.get("valuation_pb") or "—"),
        "valuation_cell": str(row.get("valuation_tier", "")) + ("*" if flagged else ""),
        "flagged": flagged,
    }


def format_quote_time(quotes: dict[str, dict]) -> str:
    stamps = [str(q.get("quote_time") or "") for q in quotes.values()]
    stamps = [s for s in stamps if len(s) >= 12]
    if not stamps:
        return ""
    t = max(stamps)
    return f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
    excluded: list[dict[str, str]],
    as_of: str,
    quotes: dict[str, dict] | None = None,
) -> list[str]:
    """渲染阅读版 MD；返回越带顶待复核的代码列表（§6.2.1.6）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    quotes = quotes or {}
    total = len(rows) + len(excluded)
    quote_line = (
        f"现价更新：{format_quote_time(quotes)}（腾讯行情快照，{len(quotes)}/{total} 只成功）"
        if quotes
        else "现价未刷新（--quotes skip；现价/带位/空间按估值时点价展示）"
    )
    lines = [
        "# A股核心估值合格池",
        "",
        f"生成日期：{as_of}｜{quote_line}",
        "",
        "本文件由 `scripts/build_a_share_core_valuation_pool.py` 生成，是 L1-L4 全量估值结论阅读版；文末附高估/无法估值排除名单（不参与量价扫描，仅事件驱动复核）。可买资格不单列：由 质量×估值 按 §6.2.1 矩阵判定（未过矩阵的组合即 watch_only 可见不可买，机器口径见池 CSV `pool_layer`）。",
        "",
        "- 现价/PE/PB 为每日扫描时的行情快照（PE 为 TTM 口径）；现价缺失（停牌/请求失败）的行沿用估值时点值。",
        "- 带位 = 现价在合理价区间内的位置（↑越带顶 / ↓低于带底）；空间 = 区间中值相对现价的涨跌幅，正数代表上行空间。",
        "- 估值列带 `*` = 现价已升破带顶：按 §6.2.1 执行说明 6 以「可接受较高估」口径对待、触发 §7.4.7 express 复核；复核前失去常备买入资格（L1 须另核 §6.6 上修/催化条件）。",
        "- 合理价区间为该股按其策略模型处于「中性」档的价格带（换算依据见池 CSV `fair_price_basis`）。",
        "",
        "| 代码 | 名称 | 质量 | 估值 | 策略 | 估值价 | 现价 | 合理价区间 | 带位 | 空间 | PE | PB |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    flagged: list[str] = []
    for row in rows:
        cells = display_cells(row, quotes.get(row["security_code"]))
        if cells["flagged"]:
            flagged.append(f"{row['security_code']}{row['security_name']}")
        lines.append(
            "| {security_code} | {security_name} | {quality_tier_label} | ".format(**row)
            + str(cells["valuation_cell"])
            + " | {strategy_tag} | {valuation_price} | ".format(**row)
            + f"{cells['price']} | {cells['band']} | {cells['band_pos']} | {cells['upside']} | {cells['pe']} | {cells['pb']} |"
        )
    lines.extend(
        [
            "",
            f"## 高估/无法估值排除名单（{len(excluded)} 家，不参与量价扫描，仅列示；估值复定由 §7 事件/财报触发）",
            "",
            "| 代码 | 名称 | 质量 | 估值 | 估值价 | 现价 | 合理价区间 | 带位 | 空间 | PE | PB | 核心理由 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in excluded:
        reason = (row.get("valuation_reason") or "").replace("|", "、").replace("\n", " ")
        if len(reason) > 80:
            reason = reason[:80] + "…"
        cells = display_cells(row, quotes.get(row["security_code"]))
        lines.append(
            "| {security_code} | {security_name} | {quality_tier_label} | {valuation_tier} | {valuation_price} | ".format(**row)
            + f"{cells['price']} | {cells['band']} | {cells['band_pos']} | {cells['upside']} | {cells['pe']} | {cells['pb']} | "
            + reason
            + " |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return flagged


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
                "decision_type": "scan_watch_only" if row["pool_layer"] == "watch_only" else "core_valuation_eligible",
                "decision_result": (
                    f"watch_only({row['valuation_tier']})" if row["pool_layer"] == "watch_only" else row["valuation_tier"]
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


def log_price_refresh(
    log_file: Path,
    as_of: str,
    quote_count: int,
    total: int,
    flagged: list[str],
    output_md: Path,
) -> None:
    """--md-only 现价刷新只写一行汇总日志，不重复逐股池结论。"""
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
                "decision_result": f"quotes {quote_count}/{total}; band_top_flagged {len(flagged)}",
                "summary_reason": ("越带顶待复核（§7.4.7）：" + "、".join(flagged)) if flagged else "无越带顶标的",
                "input_files": "",
                "source_urls": "https://qt.gtimg.cn/",
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
        help="fetch = 拉取腾讯批量行情快照，MD 按现价刷新（§6.7.6 每日扫描用）。",
    )
    parser.add_argument(
        "--md-only",
        action="store_true",
        help="只重渲染阅读版 MD（每日现价刷新）：不重写池 CSV，不逐股写池结论日志，只记一行刷新汇总。",
    )
    parser.add_argument("--timeout", type=float, default=8.0, help="行情请求超时（秒）。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows, excluded = build_pool(load_csv(args.valuation), load_csv(args.tiers), args.as_of)
    quotes: dict[str, dict] = {}
    if args.quotes == "fetch":
        items = [(row["security_code"], row.get("exchange", "")) for row in rows + excluded]
        quotes = fetch_spot_quotes(items, timeout=args.timeout)
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
        "valuation_price_as_of",
        "evidence_available_at",
        "pool_as_of",
        "source_file",
    ]
    if not args.md_only:
        write_csv(args.output_csv, rows, fieldnames)
    flagged = write_markdown(args.output_md, rows, excluded, args.as_of, quotes)
    if args.md_only:
        log_price_refresh(args.log_file, args.as_of, len(quotes), len(rows) + len(excluded), flagged, args.output_md)
        print(
            f"refreshed {args.output_md} with {len(quotes)}/{len(rows) + len(excluded)} quotes; "
            f"band-top flagged: {'、'.join(flagged) if flagged else '无'}"
        )
    else:
        log_pool_decisions(
            args.log_file,
            rows,
            args.as_of,
            args.valuation,
            args.tiers,
            args.output_csv,
            args.output_md,
        )
        print(
            f"wrote {len(rows)} pool rows to {args.output_csv}; {len(excluded)} excluded rows listed in {args.output_md}"
            + (f"; band-top flagged: {'、'.join(flagged)}" if flagged else "")
        )


if __name__ == "__main__":
    main()
