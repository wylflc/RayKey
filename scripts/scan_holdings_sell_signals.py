#!/usr/bin/env python3
"""Scan A-share holdings for stop-loss, lockup, profit-exit, and stop-raise actions.

Deterministic part of operation-workflow Stage 5. It does NOT decide hard-exit
exceptions (§16 veto / sudden event / severe quarterly miss) or thesis/valuation
sells; those are left to model judgment per the workflow's script/LLM split.
"""

from __future__ import annotations

import argparse
import csv
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

from workflow_decision_log import WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_actions.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/daily_holdings_tracker.md"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

BASE_BUILD_AMOUNT = 250_000  # 25 万元
# Cumulative sell ceiling (fraction of initial_shares) by profit level.
PROFIT_LADDER = ((2.0, 0.50), (1.0, 0.35), (0.5, 0.20), (0.3, 0.10))
LOCKUP_MONTHS = 3
SINGLE_STOCK_WEIGHT_LIMIT = 0.30
# §14 趋势保护线（v12 全部日线化）：档位 -> (均线窗口, 连续N日, 缓冲X)。
TREND_PARAMS = {
    "daily": (60, 3, 0.03),
    "weekly": (150, 5, 0.03),
    "monthly": (250, 10, 0.05),
}


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def to_float(value: object) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


def infer_secid(code: str, exchange: str) -> str:
    code = code.zfill(6)
    exchange = (exchange or "").upper()
    if exchange in {"SSE", "SH"} or code.startswith(("60", "68", "69")):
        return f"1.{code}"
    if exchange in {"BSE", "BJ"} or code.startswith(("43", "83", "87", "88", "92")):
        return f"0.{code}"  # Eastmoney serves BSE under market 0 as well
    return f"0.{code}"


def fetch_daily(code: str, exchange: str, as_of: str, timeout: float) -> tuple[str, list[str], list[float]]:
    query = urllib.parse.urlencode(
        {
            "secid": infer_secid(code, exchange),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1",
            "beg": "20200101",
            "end": as_of.replace("-", ""),
            "lmt": "1000",
        }
    )
    url = f"{EASTMONEY_KLINE}?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    klines = (payload.get("data") or {}).get("klines") or []
    dates = [line.split(",")[0] for line in klines]
    closes = [float(line.split(",")[2]) for line in klines]
    return url, dates, closes


def moving_average(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def rolling_ma(closes: list[float], window: int, back: int = 0) -> float | None:
    """MA over `window` values ending `back` bars before the last bar."""
    end = len(closes) - back
    if end < window:
        return None
    return sum(closes[end - window : end]) / window


def trend_protection_level(row: dict[str, str]) -> str:
    """趋势保护线档位：显式列优先，否则按 strategy_tag 映射（A/F/G→monthly，B/C/D/E→weekly）。"""
    level = (row.get("trend_protection_level") or "").strip().lower()
    if level in {"daily", "weekly", "monthly"}:
        return level
    tag = (row.get("strategy_tag") or "").strip().upper()[:1]
    if tag in {"A", "F", "G"}:
        return "monthly"
    return "weekly"


def months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def current_build_amount(total_assets: float) -> int:
    build = BASE_BUILD_AMOUNT
    while total_assets >= build * 20:
        build *= 2
    return build


def profit_ladder_ceiling(profit_pct: float) -> float:
    for threshold, ceiling in PROFIT_LADDER:
        if profit_pct >= threshold:
            return ceiling
    return 0.0


def classify_holding(row: dict[str, str], as_of: date, timeout: float) -> dict[str, object]:
    code = (row.get("security_code") or "").zfill(6)
    result: dict[str, object] = {key: row.get(key, "") for key in row}
    result["security_code"] = code

    cost = to_float(row.get("cost_basis"))
    stop = to_float(row.get("stop_loss_price"))
    initial_shares = to_float(row.get("initial_shares")) or 0.0
    current_shares = to_float(row.get("current_shares"))
    if current_shares is None:
        current_shares = initial_shares
    cumulative_trim = to_float(row.get("cumulative_trim_pct")) or 0.0

    try:
        data_source, dates, closes = fetch_daily(code, row.get("exchange", ""), as_of.isoformat(), timeout)
        if not closes:
            raise RuntimeError("empty kline response")
        close = closes[-1]
    except Exception as exc:  # noqa: BLE001 - provider failures must not abort the batch.
        result.update({"holdings_action": "data_error", "action_reason": repr(exc),
                       "data_source": "", "scanned_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return result

    ma120 = moving_average(closes, 120)
    ma60 = moving_average(closes, 60)
    profit_pct = (close / cost - 1) if cost else None
    entry = row.get("entry_date", "").strip()
    months_held = months_between(date.fromisoformat(entry), as_of) if entry else None
    lockup_active = months_held is not None and months_held < LOCKUP_MONTHS

    position_value = (current_shares or 0.0) * close
    ceiling = profit_ladder_ceiling(profit_pct) if profit_pct is not None else 0.0
    additional_trim_pct = max(0.0, ceiling * 100 - cumulative_trim)

    # Stop-raise suggestion: only up, and never above MA120.
    raise_stop = bool(stop is not None and ma120 is not None and ma120 > stop and close > stop * 1.1)
    suggested_stop = round(ma120, 2) if raise_stop else ""

    # 趋势保护线（§14 v12）：三档统一日线判定——连续N日收盘低于保护线，且最新收盘距线跌幅>X%。
    level = trend_protection_level(row)
    window, confirm_days, buffer_pct = TREND_PARAMS[level]
    trend_break = False
    trend_line = rolling_ma(closes, window)
    trend_ref: float | None = None
    if trend_line is not None and len(closes) >= window + confirm_days:
        below_n = all(
            closes[-i] < (rolling_ma(closes, window, i - 1) or float("inf"))
            for i in range(1, confirm_days + 1)
        )
        trend_break = below_n and close < trend_line * (1 - buffer_pct)
        trend_ref = close

    trend_actions = {
        "daily": "trend_exit_suggested",
        "weekly": "trend_reduce_half_suggested",
        "monthly": "trend_downgrade_suggested",
    }

    # Deterministic action priority (forced_exit is decided by the model, not here).
    if stop is not None and close <= stop:
        action, reason = "stop_loss_sell", f"现价 {close} <= 割肉价 {stop}，无条件清仓"
    elif lockup_active:
        action, reason = "hold", f"持有约 {months_held} 个月 (<{LOCKUP_MONTHS})，锁定期内仅持有"
        if trend_break:
            reason += f"；趋势保护线({level})已破位，锁定期内不出卖出建议，建议复核并上调割肉价"
    elif trend_break:
        action = trend_actions[level]
        reason = (
            f"趋势保护线({level}=MA{window})破位：连续{confirm_days}日收盘低于线且距线>{buffer_pct:.0%}，"
            f"现收盘 {trend_ref} < 保护线 {round(trend_line, 3)}，按分档动作复核（战术退出/减半/降档），非自动卖出"
        )
    elif profit_pct is not None and profit_pct > 0 and additional_trim_pct > 0:
        action = "trim_eligible"
        reason = f"持有>{LOCKUP_MONTHS}月且浮盈 {profit_pct:.0%}，允许累计卖出上限 {ceiling:.0%}，本次最多再卖 {additional_trim_pct:.0f}% 初始仓"
    else:
        action, reason = "hold", "无机械卖出触发"

    result.update(
        {
            "as_of": as_of.isoformat(),
            "close": round(close, 3),
            "cost_basis": cost if cost is not None else "",
            "profit_pct": round(profit_pct, 4) if profit_pct is not None else "",
            "months_held": months_held if months_held is not None else "",
            "lockup_active": lockup_active,
            "stop_loss_price": stop if stop is not None else "",
            "stop_hit": bool(stop is not None and close <= stop),
            "ma60": round(ma60, 3) if ma60 is not None else "",
            "ma120": round(ma120, 3) if ma120 is not None else "",
            "raise_stop_suggested": raise_stop,
            "suggested_stop_price": suggested_stop,
            "trend_protection_level": level,
            "trend_line_value": round(trend_line, 3) if trend_line is not None else "",
            "trend_ref_close": round(trend_ref, 3) if trend_ref is not None else "",
            "trend_break": trend_break,
            "initial_shares": initial_shares,
            "current_shares": current_shares,
            "cumulative_trim_pct": cumulative_trim,
            "profit_trim_ceiling_pct": round(ceiling * 100, 1),
            "additional_trim_pct_allowed": round(additional_trim_pct, 1),
            "position_value": round(position_value, 2),
            "holdings_action": action,
            "action_reason": reason,
            "forced_exit_review": "pending_model_review",
            "data_source": data_source,
            "scanned_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return result


def add_weights(rows: list[dict[str, object]]) -> tuple[float, int]:
    total = sum(float(r.get("position_value") or 0.0) for r in rows if r.get("holdings_action") != "data_error")
    for row in rows:
        value = float(row.get("position_value") or 0.0)
        weight = value / total if total else 0.0
        row["current_weight_pct"] = round(weight * 100, 2)
        row["weight_over_limit"] = bool(weight > SINGLE_STOCK_WEIGHT_LIMIT)
    return total, current_build_amount(total)


def scan(rows: list[dict[str, str]], as_of: date, symbols: set[str] | None, timeout: float, workers: int) -> list[dict[str, object]]:
    eligible = [r for r in rows if r.get("security_code") and (not symbols or r["security_code"].zfill(6) in symbols)]
    if not eligible:
        return []
    by_code: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(classify_holding, r, as_of, timeout): r["security_code"].zfill(6) for r in eligible}
        for future in as_completed(futures):
            by_code[futures[future]] = future.result()
    return [by_code[r["security_code"].zfill(6)] for r in eligible if r["security_code"].zfill(6) in by_code]


def write_markdown(path: Path, rows: list[dict[str, object]], as_of: date, total_assets: float, build_amount: int) -> None:
    groups = [
        ("今日割肉清仓", "stop_loss_sell"),
        ("今日趋势保护触发：战术退出复核", "trend_exit_suggested"),
        ("今日趋势保护触发：减半复核（MA150档破位）", "trend_reduce_half_suggested"),
        ("今日趋势保护触发：降档复核（MA250档破位）", "trend_downgrade_suggested"),
        ("今日止盈资格（<=允许上限）", "trim_eligible"),
        ("维持持有", "hold"),
        ("数据异常", "data_error"),
    ]
    lines = [
        "# A股每日持仓动作",
        "",
        f"日期：{as_of.isoformat()}",
        f"账户总资产（持仓市值，原则上不持现金）：{total_assets:,.0f}",
        f"当前建仓金额 build_amount：{build_amount:,.0f}",
        "账户回撤状态：需结合账户净值峰值人工判断（脚本未计算）。",
        "",
        "> 硬离场例外（§16 一票否决 / 公司突发事件 / 季报利润严重不及预期）需由模型复核 `forced_exit_review`，可打破 3 个月锁定立即清仓。",
        "",
    ]
    for title, action in groups:
        members = [r for r in rows if r.get("holdings_action") == action]
        lines.extend([f"## {title}", ""])
        if not members:
            lines.extend(["无。", ""])
            continue
        for index, row in enumerate(members, 1):
            lines.append(f"{index}. {row.get('security_name','')}（{row.get('security_code','')}）")
            lines.append(f"- 策略/质量/估值：{row.get('strategy_tag','')} / {row.get('quality_tier','')} / {row.get('valuation_tier','')}")
            lines.append(f"- 现价/成本/浮盈：{row.get('close','')} / {row.get('cost_basis','')} / {row.get('profit_pct','')}")
            lines.append(f"- 持有月数/锁定：{row.get('months_held','')} / {row.get('lockup_active','')}")
            lines.append(f"- 割肉价/MA120/上调建议：{row.get('stop_loss_price','')} / {row.get('ma120','')} / {row.get('suggested_stop_price','') or '-'}")
            lines.append(f"- 趋势保护：{row.get('trend_protection_level','')} 线 {row.get('trend_line_value','') or '-'}，参考收盘 {row.get('trend_ref_close','') or '-'}，破位 {row.get('trend_break','')}")
            lines.append(f"- 当前权重：{row.get('current_weight_pct','')}%{'（超30%）' if row.get('weight_over_limit') else ''}")
            lines.append(f"- 触发：{row.get('action_reason','')}")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def log_decisions(log_file: Path, rows: list[dict[str, object]], as_of: date, holdings_file: Path, output_csv: Path, output_md: Path) -> None:
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries = [
        {
            "logged_at_utc": logged_at,
            "workflow_stage": "holdings_sell_scan",
            "run_id": f"holdings_sell_scan:{as_of.isoformat()}",
            "as_of": as_of.isoformat(),
            "security_code": row.get("security_code", ""),
            "security_name": row.get("security_name", ""),
            "decision_type": "holdings_action",
            "decision_result": row.get("holdings_action", ""),
            "summary_reason": row.get("action_reason", ""),
            "input_files": str(holdings_file),
            "source_urls": row.get("data_source", ""),
            "output_file": f"{output_csv};{output_md}",
            "operator_or_script": "scripts/scan_holdings_sell_signals.py",
            "workflow_version": WORKFLOW_VERSION,
        }
        for row in rows
    ]
    append_decision_log(log_file, entries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Trading date in YYYY-MM-DD format.")
    parser.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="Optional comma-separated security codes to filter holdings.")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


FIELDNAMES = [
    "as_of", "security_code", "security_name", "strategy_tag", "quality_tier", "valuation_tier",
    "entry_date", "months_held", "lockup_active", "cost_basis", "close", "profit_pct",
    "stop_loss_price", "stop_hit", "ma60", "ma120", "raise_stop_suggested", "suggested_stop_price",
    "trend_protection_level", "trend_line_value", "trend_ref_close", "trend_break",
    "initial_shares", "current_shares", "cumulative_trim_pct", "profit_trim_ceiling_pct",
    "additional_trim_pct_allowed", "position_value", "current_weight_pct", "weight_over_limit",
    "holdings_action", "action_reason", "forced_exit_review", "data_source", "scanned_at_utc",
]


def main() -> None:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    symbols = {item.strip().zfill(6) for item in args.symbols.split(",") if item.strip()} or None
    holdings = load_csv(args.holdings) if args.holdings.exists() else []
    rows = scan(holdings, as_of, symbols, args.timeout, args.workers)
    total_assets, build_amount = add_weights(rows)
    write_csv(args.output_csv, rows, FIELDNAMES)
    write_markdown(args.output_md, rows, as_of, total_assets, build_amount)
    if rows:
        log_decisions(args.log_file, rows, as_of, args.holdings, args.output_csv, args.output_md)
    print(f"scanned {len(rows)} holdings; total_assets={total_assets:,.0f}; build_amount={build_amount:,.0f}")


if __name__ == "__main__":
    main()
