#!/usr/bin/env python3
"""Screen daily A-share volume-price signals from the core valuation pool."""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_buy_candidates.csv"
DEFAULT_OUTPUT_MD = ROOT / "data/processed/daily_volume_price_tracker.md"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"


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


def infer_secid(code: str, exchange: str) -> str:
    code = code.zfill(6)
    exchange = (exchange or "").upper()
    if exchange == "SSE" or code.startswith(("60", "68", "69")):
        return f"1.{code}"
    return f"0.{code}"


def get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def fetch_daily_rows(code: str, exchange: str, as_of: str, timeout: float) -> tuple[str, list[dict[str, float | str]]]:
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
    payload = get_json(url, timeout)
    klines = (payload.get("data") or {}).get("klines") or []
    rows: list[dict[str, float | str]] = []
    for line in klines:
        parts = line.split(",")
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "pct_chg": float(parts[8]),
            }
        )
    return url, rows


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values)


def ema(values: list[float], span: int) -> list[float]:
    alpha = 2 / (span + 1)
    result: list[float] = []
    current: float | None = None
    for value in values:
        current = value if current is None else alpha * value + (1 - alpha) * current
        result.append(current)
    return result


def add_indicators(rows: list[dict[str, float | str]]) -> None:
    closes = [float(row["close"]) for row in rows]
    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema(dif, 9)

    for index, row in enumerate(rows):
        for window in (5, 10, 20, 60, 120, 240):
            if index + 1 >= window:
                row[f"ma{window}"] = mean(float(item["close"]) for item in rows[index + 1 - window : index + 1])
        for window in (5, 20, 60):
            if index + 1 >= window:
                row[f"vol_ma{window}"] = mean(float(item["volume"]) for item in rows[index + 1 - window : index + 1])
        for window in (60, 120, 250, 500, 750):
            if index >= window:
                row[f"prev_high_{window}"] = max(float(item["high"]) for item in rows[index - window : index])
        high = float(row["high"])
        low = float(row["low"])
        row["close_location"] = (float(row["close"]) - low) / (high - low) if high > low else 0.0
        row["macd_dif"] = dif[index]
        row["macd_dea"] = dea[index]


def pct_return(rows: list[dict[str, float | str]], index: int, window: int) -> float | None:
    if index < window:
        return None
    return float(rows[index]["close"]) / float(rows[index - window]["close"]) - 1


def volume_percentile(rows: list[dict[str, float | str]], index: int, window: int = 120) -> float | None:
    if index + 1 < window:
        return None
    values = [float(row["volume"]) for row in rows[index + 1 - window : index + 1]]
    current = float(rows[index]["volume"])
    return 100 * sum(1 for value in values if value <= current) / len(values)


def classify_signal(rows: list[dict[str, float | str]]) -> dict[str, object]:
    add_indicators(rows)
    index = len(rows) - 1
    row = rows[index]
    if index < 60 or "ma20" not in row or "ma60" not in row or "vol_ma20" not in row:
        return {"signal_state": "insufficient_price_history", "signals": []}

    close = float(row["close"])
    ma20 = float(row["ma20"])
    ma60 = float(row["ma60"])
    vol_ma20 = float(row["vol_ma20"])
    day_vol_ratio = float(row["volume"]) / vol_ma20
    vol_3d_ratio = mean(float(item["volume"]) for item in rows[index - 2 : index + 1]) / vol_ma20
    vol_5d_ratio = mean(float(item["volume"]) for item in rows[index - 4 : index + 1]) / vol_ma20
    baseline = mean(float(item["volume"]) for item in rows[index - 59 : index - 19])
    vol_5d_ratio_baseline = mean(float(item["volume"]) for item in rows[index - 4 : index + 1]) / baseline
    baseline_days = sum(1 for item in rows[index - 4 : index + 1] if float(item["volume"]) > baseline * 1.2)
    vol_percentile = volume_percentile(rows, index) or 0.0
    ret_5d = pct_return(rows, index, 5) or 0.0
    ret_20d = pct_return(rows, index, 20) or 0.0
    ret_60d = pct_return(rows, index, 60) or 0.0

    effective_volume = (
        day_vol_ratio >= 1.8
        or vol_3d_ratio >= 1.5
        or vol_5d_ratio >= 1.4
        or (vol_5d_ratio_baseline >= 1.6 and baseline_days >= 3)
        or (
            float(row.get("vol_ma5", 0.0)) > vol_ma20 > float(row.get("vol_ma60", math.inf))
            and float(row.get("vol_ma5", 0.0)) / float(row.get("vol_ma60", math.inf)) >= 1.5
        )
        or (vol_percentile >= 80 and ret_5d > 0.03)
    )

    daily_bull = close > float(row.get("ma5", math.inf)) > float(row.get("ma10", math.inf)) > ma20 > ma60
    strong_daily_bull = daily_bull and ma60 > float(row.get("ma120", math.inf)) > float(row.get("ma240", math.inf))
    quasi_bull = (
        close > float(row.get("ma5", math.inf)) > float(row.get("ma10", math.inf)) > ma20
        and close > ma60
        and ma20 >= float(rows[index - 5].get("ma20", ma20))
    )
    close_location = float(row["close_location"])
    break_periods: list[str] = []
    for window in (60, 120, 250, 500, 750):
        previous_high = row.get(f"prev_high_{window}")
        if previous_high is not None and close > float(previous_high) * 1.005:
            break_periods.append(str(window))

    signals: list[str] = []
    wait_reasons: list[str] = []
    if break_periods and effective_volume and close_location >= 0.6:
        signals.append(f"8.7.1 放量突破前高({','.join(break_periods)}日)")
    elif break_periods and effective_volume:
        wait_reasons.append("前高突破但收盘位置不足")

    if close > ma20 and close > ma60 and effective_volume and close_location >= 0.6 and (daily_bull or quasi_bull):
        signals.append("8.7.2 放量突破关键均线/趋势启动")
    elif close > ma20 and close > ma60 and effective_volume and (daily_bull or quasi_bull):
        wait_reasons.append("均线突破但收盘位置不足")

    up_days = sum(1 for item in rows[index - 4 : index + 1] if float(item["close"]) > float(item["open"]))
    if up_days >= 4 and 0.08 <= ret_5d <= 0.25 and daily_bull and not (close_location < 0.4 and day_vol_ratio >= 1.8):
        signals.append("8.7.4 连续上涨")

    macd_cross_recent = any(
        float(rows[j - 1]["macd_dif"]) <= float(rows[j - 1]["macd_dea"])
        and float(rows[j]["macd_dif"]) > float(rows[j]["macd_dea"])
        for j in range(max(1, index - 2), index + 1)
    )
    if daily_bull and 0.03 <= ret_20d <= 0.20 and 1.1 <= vol_5d_ratio <= 1.8 and macd_cross_recent:
        signals.append("8.7.5 温和放量多头")

    # 8.7 核心原则：有效放量且当日收涨即列买入候选，不要求突破前高或关键均线。
    if effective_volume and float(row["pct_chg"]) > 0:
        signals.append("8.7.0 放量上涨")

    overextended = close / ma20 - 1 > 0.25 or ret_5d > 0.30 or ret_20d > 0.60
    if overextended:
        signal_state = "wait_pullback"
        action_bias = "等回踩"
    elif signals:
        signal_state = "buy_candidate"
        action_bias = "可建目标仓位1/3"
    elif wait_reasons:
        signal_state = "wait_confirmation"
        action_bias = "等确认"
    elif close < ma60:
        signal_state = "wait_repair"
        action_bias = "仅观察"
    else:
        signal_state = "wait_breakout"
        action_bias = "仅观察"

    # §8.11 买入候选强势跟踪：强势程度仅由中短期量价走势判定。
    ma5_v = float(row.get("ma5", close))
    ma10_v = float(row.get("ma10", close))
    short_strong = close > ma5_v >= ma10_v and ret_5d > 0 and vol_5d_ratio >= 1.1
    mid_strong = close > ma20 and close > ma60 and ret_20d > 0
    short_weak = close < ma5_v and ret_5d < 0
    mid_weak = close < ma20 or close < ma60
    trend_strength = "strong" if (short_strong and mid_strong) else "weakening" if (short_weak and mid_weak) else "neutral"

    # §8.7 信号分级：放量 × 短期多头 × 突破确认 → 强/中/弱（仅对买入候选）。
    if signal_state == "buy_candidate":
        breakout_confirm = any(sig.startswith(("8.7.1", "8.7.2")) for sig in signals)
        if (daily_bull or quasi_bull) and breakout_confirm:
            signal_grade, action_bias = "强", "可建目标仓位1/3"
        elif daily_bull or quasi_bull:
            signal_grade, action_bias = "中", "可小仓试探或等确认"
        else:
            signal_grade, action_bias = "弱", "等确认"
    else:
        signal_grade = ""

    return {
        "trade_date": row["date"],
        "close": close,
        "high": row["high"],
        "low": row["low"],
        "pct_chg": row["pct_chg"],
        "amount": row["amount"],
        "ma5": row.get("ma5", ""),
        "ma10": row.get("ma10", ""),
        "ma20": ma20,
        "ma60": ma60,
        "ma120": row.get("ma120", ""),
        "ma240": row.get("ma240", ""),
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "ret_60d": ret_60d,
        "day_vol_ratio_20": day_vol_ratio,
        "vol_3d_ratio_20": vol_3d_ratio,
        "vol_5d_ratio_20": vol_5d_ratio,
        "vol_5d_ratio_baseline": vol_5d_ratio_baseline,
        "vol_percentile_120": vol_percentile,
        "close_location": close_location,
        "effective_volume": effective_volume,
        "daily_bull": daily_bull,
        "strong_daily_bull": strong_daily_bull,
        "quasi_bull": quasi_bull,
        "break_periods": ",".join(break_periods),
        "signals": "; ".join(signals),
        "wait_reasons": "; ".join(wait_reasons),
        "overextended": overextended,
        "signal_state": signal_state,
        "priority": "",
        "action_bias": action_bias,
        "signal_grade": signal_grade,
        "trend_strength": trend_strength,
    }


def fetch_market_state(as_of: str, timeout: float) -> str:
    """§8.12：沪深300 收盘与 MA200 判定市场状态（强势/弱势/震荡）。"""
    try:
        _, rows = fetch_daily_rows("000300", "SSE", as_of, timeout)
        closes = [float(row["close"]) for row in rows]
        if len(closes) < 221:
            return "震荡"
        ma200_now = mean(closes[-200:])
        ma200_prev = mean(closes[-220:-20])
        close = closes[-1]
        if close > ma200_now and ma200_now > ma200_prev:
            return "强势"
        if close < ma200_now and ma200_now < ma200_prev:
            return "弱势"
        return "震荡"
    except Exception:  # noqa: BLE001 - index availability must not break the stock scan.
        return "未知"


def rounded(value: object, digits: int = 4) -> object:
    if isinstance(value, float):
        return round(value, digits)
    return value


def assign_priority(row: dict[str, object]) -> str:
    if row.get("signal_state") != "buy_candidate":
        return ""
    quality_tier = str(row.get("quality_tier", ""))
    valuation_tier = str(row.get("valuation_tier", ""))
    break_periods = set(str(row.get("break_periods", "")).split(","))
    if quality_tier == "L1" and valuation_tier in {"低估", "较低估", "中性"} and break_periods.intersection({"120", "250", "500", "750"}):
        return "S"
    if quality_tier in {"L1", "L2"} and valuation_tier in {"低估", "较低估", "中性"}:
        return "A"
    if quality_tier in {"L1", "L2"} and valuation_tier == "可接受较高估":
        return "B"
    return "C"


def scan_one(pool_row: dict[str, str], as_of: str, timeout: float) -> dict[str, object]:
    code = pool_row["security_code"].zfill(6)
    try:
        kline_url, price_rows = fetch_daily_rows(code, pool_row.get("exchange", ""), as_of, timeout)
        if not price_rows:
            raise RuntimeError("empty kline response")
        signal = classify_signal(price_rows)
    except Exception as exc:  # noqa: BLE001 - data-provider failures should not abort the batch.
        kline_url = ""
        signal = {
            "trade_date": as_of,
            "signal_state": "data_error",
            "signals": "",
            "wait_reasons": repr(exc),
            "priority": "",
            "action_bias": "仅观察",
        }
    signal.update(pool_row)
    signal["security_code"] = code
    signal["priority"] = assign_priority(signal)
    signal["data_source"] = kline_url
    signal["screened_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {key: rounded(value) for key, value in signal.items()}


def scan(input_rows: list[dict[str, str]], as_of: str, symbols: set[str] | None, timeout: float, workers: int) -> list[dict[str, object]]:
    eligible_rows = []
    for pool_row in input_rows:
        code = pool_row["security_code"].zfill(6)
        if symbols and code not in symbols:
            continue
        eligible_rows.append(pool_row)
    if not eligible_rows:
        return []

    results_by_code: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(scan_one, row, as_of, timeout): row["security_code"].zfill(6) for row in eligible_rows}
        for future in as_completed(futures):
            code = futures[future]
            results_by_code[code] = future.result()
    return [results_by_code[row["security_code"].zfill(6)] for row in eligible_rows if row["security_code"].zfill(6) in results_by_code]


def write_markdown(path: Path, rows: list[dict[str, object]], as_of: str, market_state: str) -> None:
    groups = [
        ("今日买入候选", "buy_candidate"),
        ("今日等待回踩", "wait_pullback"),
        ("今日等待确认", "wait_confirmation"),
        ("今日等待突破", "wait_breakout"),
        ("今日等待修复", "wait_repair"),
    ]
    lines = [
        "# A股每日量价跟踪",
        "",
        f"日期：{as_of}",
        f"市场状态：{market_state}（§8.12，沪深300 vs MA200；弱势时操作偏向下调一档）",
        "数据口径：东方财富前复权日线；仅扫描 `data/processed/a_share_core_valuation_pool.csv`。",
        "",
    ]
    for title, state in groups:
        lines.extend([f"## {title}", ""])
        members = [row for row in rows if row.get("signal_state") == state]
        if not members:
            lines.extend(["无。", ""])
            continue
        for index, row in enumerate(members, 1):
            lines.append(f"{index}. {row['security_name']}（{row['security_code']}）")
            lines.append(f"- 优先级：{row.get('priority') or '-'}")
            lines.append(f"- 信号分级：{row.get('signal_grade') or '-'}")
            lines.append(f"- 质量/估值/策略：{row.get('quality_tier')} / {row.get('valuation_tier')} / {row.get('strategy_tag')}")
            lines.append(f"- 触发信号：{row.get('signals') or row.get('wait_reasons') or '-'}")
            lines.append(
                "- 量价指标：收盘 {close}，5日 {ret_5d:.2%}，20日 {ret_20d:.2%}，"
                "vol3 {vol_3d_ratio_20}，vol5 {vol_5d_ratio_20}，收盘位置 {close_location}".format(**row)
            )
            lines.append(f"- 操作偏向：{row.get('action_bias')}")
            lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def log_scan_decisions(
    log_file: Path,
    rows: list[dict[str, object]],
    as_of: str,
    input_file: Path,
    output_csv: Path,
    output_md: Path,
) -> None:
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: list[dict[str, object]] = []
    for row in rows:
        reason = row.get("signals") or row.get("wait_reasons") or row.get("action_bias") or ""
        entries.append(
            {
                "logged_at_utc": logged_at,
                "workflow_stage": "daily_volume_price_scan",
                "run_id": f"daily_volume_price_scan:{as_of}",
                "as_of": as_of,
                "security_code": row.get("security_code", ""),
                "security_name": row.get("security_name", ""),
                "decision_type": "daily_signal_state",
                "decision_result": row.get("signal_state", ""),
                "summary_reason": reason,
                "input_files": str(input_file),
                "source_urls": row.get("data_source", ""),
                "output_file": f"{output_csv};{output_md}",
                "operator_or_script": "scripts/screen_daily_volume_price_signals.py",
                "workflow_version": WORKFLOW_VERSION,
            }
        )
    append_decision_log(log_file, entries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="Trading date in YYYY-MM-DD format.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="Optional comma-separated security codes to filter the input pool.")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-request network timeout in seconds.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel data-provider requests.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    symbols = {item.strip().zfill(6) for item in args.symbols.split(",") if item.strip()} or None
    input_rows = load_csv(args.input)
    market_state = fetch_market_state(args.as_of, args.timeout)
    rows = scan(input_rows, args.as_of, symbols, args.timeout, args.workers)
    for row in rows:
        row["market_state"] = market_state
        # §8.12：弱势市场下各信号分级的操作偏向下调一档。
        if market_state == "弱势" and row.get("signal_state") == "buy_candidate":
            row["action_bias"] = "可小仓试探或等确认" if row.get("signal_grade") == "强" else "等确认"
    fieldnames = [
        "trade_date",
        "security_code",
        "security_name",
        "exchange",
        "quality_tier",
        "quality_tier_label",
        "valuation_tier",
        "strategy_tag",
        "signal_state",
        "priority",
        "action_bias",
        "signal_grade",
        "trend_strength",
        "market_state",
        "signals",
        "wait_reasons",
        "close",
        "high",
        "low",
        "pct_chg",
        "amount",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "ma120",
        "ma240",
        "ret_5d",
        "ret_20d",
        "ret_60d",
        "day_vol_ratio_20",
        "vol_3d_ratio_20",
        "vol_5d_ratio_20",
        "vol_5d_ratio_baseline",
        "vol_percentile_120",
        "close_location",
        "effective_volume",
        "daily_bull",
        "strong_daily_bull",
        "quasi_bull",
        "break_periods",
        "overextended",
        "data_source",
        "screened_at_utc",
    ]
    write_csv(args.output_csv, rows, fieldnames)
    write_markdown(args.output_md, rows, args.as_of, market_state)
    log_scan_decisions(args.log_file, rows, args.as_of, args.input, args.output_csv, args.output_md)
    print(f"scanned {len(rows)} rows from {args.input}")


if __name__ == "__main__":
    main()
