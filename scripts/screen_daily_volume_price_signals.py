#!/usr/bin/env python3
"""每日行情取数（工作流 §8）＋ §9.3 机械执行层。

v4.18 起本脚本只做判定所需的事：取收盘/MA20/MA60/成交额、算 `P/V`、
§7.5 冻结排除、§9.3.2 排序-去相关-出买入计划、§8.4 缺口回溯（只报区间涨跌与放量峰值）。
已退役的信号分级/入场阶段/形态识别/市场状态/深度低估关注等展示机制于 v4.18 整体删除
（OI-063，用户 2026-08-19 裁定）——那批代码不进任何买卖判定，历史结论沉淀在回测日志 §12.8。
"""

from __future__ import annotations

import argparse
import csv
import math
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from a_share_quotes import quote_symbol
from build_a_share_core_valuation_pool import effective_valuation_tier
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_buy_candidates.csv"
DEFAULT_REVIEW_QUEUE = ROOT / "data/interim/a_share_report_update_queue.csv"
DEFAULT_MODEL_BANDS = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
DEFAULT_PLAN_OUT = ROOT / "data/processed/daily_entry_plan.csv"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 后备行情源：东财历史行情不可用/空响应时切换（同为前复权日线；成交额以收盘×量近似，仅影响流动性门槛估计）。
# 统一走腾讯 newfqkline：同构覆盖 sh/sz/bj，且为北交所唯一可用历史K线源；旧 web.ifzq 端点在批量扫描下易限流（2026-07-17 实测 501）。
TENCENT_KLINE = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

MIN_AMOUNT_MA20 = 50_000_000  # §10.1 第 3 条：20日均成交额低于 5,000 万元不列买入候选。


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
    # 北交所（92/43/83/87 前缀）：东财K线无数据，直接走腾讯 newfqkline。
    if quote_symbol(code, exchange).startswith("bj"):
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout)
    url = f"{EASTMONEY_KLINE}?{query}"
    try:
        payload = get_json(url, timeout)
    except OSError:
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout)
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout)
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


def fetch_daily_rows_tencent(code: str, exchange: str, as_of: str, timeout: float) -> tuple[str, list[dict[str, float | str]]]:
    """后备源：腾讯前复权日线（北交所主源，走 newfqkline）。成交量单位为手（口径内部一致）；
    成交额接口未提供，以收盘价×成交量×100近似，只影响流动性门槛的估计。"""
    symbol = quote_symbol(code, exchange)
    base = TENCENT_KLINE
    param = f"{symbol},day,2020-01-01,{as_of},1000,qfq"
    url = f"{base}?param={param}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    data = (payload.get("data") or {}).get(symbol) or {}
    klines = [list(parts) for parts in (data.get("qfqday") or data.get("day") or [])]
    # 腾讯前复权序列可能滞后一个交易日：用不复权序列补齐最新K线。
    # 成交量单位沪深口径不一（股/手），按重叠日成交量比例归一后再拼接。
    if klines and str(klines[-1][0]) < as_of:
        raw_url = f"{base}?param={symbol},day,{klines[-1][0]},{as_of},10,"
        raw_req = urllib.request.Request(
            raw_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
        )
        try:
            with urllib.request.urlopen(raw_req, timeout=timeout) as response:
                raw_data = (json.loads(response.read().decode("utf-8", "ignore")).get("data") or {}).get(symbol) or {}
            raw_rows = raw_data.get("day") or []
            overlap = {str(p[0]): float(p[5]) for p in raw_rows}
            qfq_last_vol = float(klines[-1][5])
            raw_same_vol = overlap.get(str(klines[-1][0]))
            vol_scale = 1.0
            if raw_same_vol and qfq_last_vol:
                ratio = raw_same_vol / qfq_last_vol
                vol_scale = 100.0 if ratio > 10 else 1.0
            for parts in raw_rows:
                if str(parts[0]) > str(klines[-1][0]) and str(parts[0]) <= as_of:
                    klines.append([parts[0], parts[1], parts[2], parts[3], parts[4], float(parts[5]) / vol_scale])
        except OSError:
            pass
    rows: list[dict[str, float | str]] = []
    prev_close: float | None = None
    for parts in klines:
        close = float(parts[2])
        volume = float(parts[5])
        pct = 0.0 if prev_close in (None, 0.0) else (close / prev_close - 1) * 100
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "close": close,
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": volume,
                "amount": close * volume * 100,
                "pct_chg": pct,
            }
        )
        prev_close = close
    return url, rows


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values)


def add_indicators(rows: list[dict[str, float | str]]) -> None:
    """§8.3 判定所需量：MA20/MA60（前复权收盘简单均线）、20日均量、20日均成交额。"""
    for index, row in enumerate(rows):
        for window in (20, 60):
            if index + 1 >= window:
                row[f"ma{window}"] = mean(float(item["close"]) for item in rows[index + 1 - window : index + 1])
        if index + 1 >= 20:
            row["vol_ma20"] = mean(float(item["volume"]) for item in rows[index + 1 - 20 : index + 1])
            row["amount_ma20"] = mean(float(item["amount"]) for item in rows[index + 1 - 20 : index + 1])


def to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def quote_snapshot(rows: list[dict[str, float | str]]) -> dict[str, object]:
    """末根K线的判定量快照。不足 60 根时 MA60 缺失，走势闸门自然不可能通过。"""
    row = rows[-1]
    if len(rows) < 60 or "ma20" not in row or "ma60" not in row:
        return {"signal_state": "insufficient_price_history"}
    return {
        "signal_state": "ok",
        "trade_date": row["date"],
        "close": float(row["close"]),
        "high": row["high"],
        "low": row["low"],
        "pct_chg": row["pct_chg"],
        "amount": row["amount"],
        "ma20": float(row["ma20"]),
        "ma60": float(row["ma60"]),
        "amount_ma20": float(row.get("amount_ma20") or 0.0),
    }


def gap_review(rows: list[dict[str, float | str]], as_of: str, since: str) -> dict[str, object]:
    """§8.4 缺口回溯：报告 since→as_of 之间未被扫描区间的交易日数、区间涨跌与最大放量。

    v4.18 起不再逐日回放信号（信号机制已删除，OI-063）；本函数只回答
    「隔了几天没扫、期间价格动了多少、有没有异常放量」。
    """
    idx = {str(r["date"]): j for j, r in enumerate(rows)}
    gap_days = [d for d in idx if since < d <= as_of]
    if len(gap_days) <= 1:
        return {}
    max_ratio, max_ratio_day = 0.0, ""
    for d in sorted(gap_days):
        j = idx[d]
        if j < 60:
            continue
        vol_ma20 = to_float(rows[j].get("vol_ma20")) or 0.0
        if vol_ma20 > 0:
            ratio = float(rows[j]["volume"]) / vol_ma20
            if ratio > max_ratio:
                max_ratio, max_ratio_day = ratio, d
    first, last = sorted(gap_days)[0], sorted(gap_days)[-1]
    ret = float(rows[idx[last]]["close"]) / float(rows[idx[first]]["open"]) - 1
    return {
        "gap_trading_days": len(gap_days),
        "gap_return": round(ret, 4),
        "gap_max_vol_ratio": round(max_ratio, 2),
        "gap_max_vol_day": max_ratio_day,
    }


def rounded(value: object, digits: int = 4) -> object:
    if isinstance(value, float):
        return round(value, digits)
    return value


def scan_one(pool_row: dict[str, str], as_of: str, timeout: float, since: str = "") -> dict[str, object]:
    code = pool_row["security_code"].zfill(6)
    try:
        kline_url, price_rows = fetch_daily_rows(code, pool_row.get("exchange", ""), as_of, timeout)
        if not price_rows:
            raise RuntimeError("empty kline response")
        add_indicators(price_rows)
        snapshot = quote_snapshot(price_rows)
        if since:
            snapshot.update(gap_review(price_rows, as_of, since))
    except Exception as exc:  # noqa: BLE001 - data-provider failures should not abort the batch.
        kline_url = ""
        snapshot = {"trade_date": as_of, "signal_state": "data_error", "note": repr(exc)}
    snapshot.update(pool_row)
    snapshot["security_code"] = code

    # §6.2 价格自动定档 + 带内位置：档位由现价 vs 合理价区间每日自动重定；无法估值不自动定档。
    close = to_float(snapshot.get("close"))
    fair_low = to_float(pool_row.get("fair_price_low"))
    fair_high = to_float(pool_row.get("fair_price_high"))
    stored_tier = pool_row.get("valuation_tier", "")
    band_position = ""
    if close and fair_low and fair_high:
        if close > fair_high:
            band_position = f"越带顶+{(close / fair_high - 1) * 100:.0f}%"
        elif close < fair_low:
            band_position = f"低于带底-{(1 - close / fair_low) * 100:.0f}%"
        else:
            pos = (close - fair_low) / (fair_high - fair_low) * 100 if fair_high > fair_low else 0.0
            band_position = f"带内{pos:.0f}%"
    effective_tier = stored_tier if stored_tier == "无法估值" else (
        effective_valuation_tier(close, fair_low, fair_high) or stored_tier
    )
    snapshot["band_position"] = band_position
    snapshot["valuation_tier_effective"] = effective_tier
    snapshot["valuation_tier_changed"] = effective_tier != stored_tier
    # 空间（区间中值 ÷ 现价 − 1）：只在现价低于带底时展示（与 §6.2 判「低估」所用同一个量）。
    snapshot["margin_of_safety"] = (
        round((fair_low + fair_high) / 2 / close - 1, 4)
        if close and fair_low and fair_high and close < fair_low else ""
    )
    snapshot["data_source"] = kline_url
    snapshot["screened_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {key: rounded(value) for key, value in snapshot.items()}


def detect_last_scan(log_path: Path, as_of: str) -> str:
    """§8.4：自动检出上一次扫描日——缺口回溯不能依赖人记得传 --since。"""
    if not log_path.exists():
        return ""
    dates = set()
    with log_path.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("decision_type") == "daily_signal_state" and row.get("as_of"):
                dates.add(row["as_of"])
    prior = sorted(d for d in dates if d < as_of)
    return prior[-1] if prior else ""


def scan(input_rows: list[dict[str, str]], as_of: str, symbols: set[str] | None, timeout: float, workers: int, since: str = "") -> list[dict[str, object]]:
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
        futures = {executor.submit(scan_one, row, as_of, timeout, since): row["security_code"].zfill(6) for row in eligible_rows}
        for future in as_completed(futures):
            code = futures[future]
            results_by_code[code] = future.result()
    return [results_by_code[row["security_code"].zfill(6)] for row in eligible_rows if row["security_code"].zfill(6) in results_by_code]


def log_scan_decisions(
    log_file: Path,
    rows: list[dict[str, object]],
    as_of: str,
    input_file: Path,
    output_csv: Path,
) -> None:
    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: list[dict[str, object]] = []
    for row in rows:
        reason = str(row.get("note") or "")
        if not reason and row.get("model_pv") != "":
            reason = f"P/V {row.get('model_pv')}"
        entries.append(
            {
                "logged_at_utc": logged_at,
                "workflow_stage": "daily_volume_price_scan",
                "run_id": f"daily_volume_price_scan:{as_of}",
                "as_of": as_of,
                "security_code": row.get("security_code", ""),
                "security_name": row.get("security_name", ""),
                # decision_type 名称保持 daily_signal_state：detect_last_scan（§8.4 缺口回溯）
                # 以它识别历史扫描日，改名会让回溯断链。
                "decision_type": "daily_signal_state",
                "decision_result": row.get("signal_state", ""),
                "summary_reason": reason,
                "input_files": str(input_file),
                "source_urls": row.get("data_source", ""),
                "output_file": str(output_csv),
                "operator_or_script": "scripts/screen_daily_volume_price_signals.py",
                "workflow_version": WORKFLOW_VERSION,
            }
        )
    append_decision_log(log_file, entries)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since",
        default="auto",
        help='§8.4 缺口回溯起点。"auto"（缺省）从决策日志检出上次扫描日；'
             '给具体日期则强制回溯该日之后；给空串关闭回溯。',
    )
    parser.add_argument("--as-of", required=True, help="Trading date in YYYY-MM-DD format.")
    parser.add_argument("--evidence-date", default="",
                        help="证据日（北京当日历日，v4.27）：模型带 available_at 的可用性截止。"
                             "晚间披露的报告官方戳次日，凌晨扫描时戳日 > 信号日——不给本参数则回退 "
                             "--as-of（信号日）作截止，当晚吸收的新带会整只失带（§6.7/§7.5 v4.27）。"
                             "每日生产扫描必须传北京当日历日；历史重放不传即旧口径。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE,
                        help="Report update queue CSV; pool stocks with buy_blocked=review_pending are frozen per §7.5.")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="Optional comma-separated security codes to filter the input pool.")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-request network timeout in seconds.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel data-provider requests.")
    # ---- §9.3 机械执行层。三个都给才出买入计划。
    parser.add_argument("--model-bands", type=Path, default=DEFAULT_MODEL_BANDS,
                        help="批量模型带表；§9.3 的 P/V 用它，不用池里的逐票档案带")
    parser.add_argument("--nav", type=float, default=0.0,
                        help="当日净资产，用于定一档 = NAV × §9.3.1 的比例。不给则只算 P/V、不出买入计划")
    parser.add_argument("--funds", type=float, default=None,
                        help="当日**可用资金 = 现金 + 未用授信**（OI-062）。买入计划以此为预算；"
                             "不给则退回「可用资金＝净资产」的旧估算并显著告警。满仓/带融资账户必须给。")
    parser.add_argument("--rf", type=float, default=0.017114,
                        help="十年国债收益率，银行股利折现用（§12.31）")
    parser.add_argument("--plan-out", type=Path, default=DEFAULT_PLAN_OUT)
    return parser.parse_args()


def load_blocked_codes(path: Path) -> set[str] | None:
    """§7.5 复核期买入冻结：更新队列中 buy_blocked=review_pending 的代码；文件缺失返回 None（未启用）。"""
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["security_code"].zfill(6)
        for row in rows
        if row.get("security_code") and (row.get("buy_blocked", "").strip() == "review_pending")
    }


# ------------------------------------------------------------------ §9.3 机械执行层
# **口径一律来自 `docs/000_Ashare_workflow.md` §9.3，此处不另立标准。** 三处细节：
#   * 走势闸门 `收 > MA20 > MA60` 用**前复权**序列（收盘与均线同尺度，除息不产生假信号）；
#   * `P/V` = **未复权现价 ÷ 当日带**。本脚本的 `close` 取自 `fqt=1` 前复权序列，
#     而前复权序列**锚在最新一根**，故 `--as-of` 为最近交易日时末根收盘即未复权现价，两者同尺度；
#     **回溯历史日期时该等式不成立**，故本层只在 `--as-of` 为最新交易日时给出买入计划。
#   * 银行走工作流 §6.5.1 的股利折现口径。
SEC93_BUY_LINE = 0.94          # §9.3.1 买入线（v4.33：对齐解 0.9434 取两位小数，用户裁定；合格面 17.823%，回测日志 §12.102）
SEC93_MAX_CORR = 0.70          # §9.3.1，252 日日收益率皮尔逊相关上限
SEC93_SCAN_DEPTH = 40          # §9.3.2 第 3 步：相关性过滤时最多下扫多少名
SEC93_TRANCHE_PCT = 0.05       # §9.3.1 单次买入比例
SEC93_LOT = 100                # A 股一手
SEC93_POSITION_CAP = None      # §9.3.1：v4.04 起**无单票上限**——用户 2026-08-17 裁定退役仓位控制，
                               # 风险改由回撤与年化承担（§12.75）。None = 不设限，判定处直接跳过。
SEC93_SELL_LINE = 2.50         # §9.3.1「减持线」，v4.33：对齐解 2.5008 取两位小数（上侧面 30.460%；2.49~2.52 回测逐位无差）：P/V ≥ 线且收盘 < MA20 → 减一档。
# ↑ 本脚本只做买入侧（§9.3.2 第 4 步卖出是人工），该常量是减持线数值的**脚本侧唯一落点**，
#   供卖出侧人工核对引用——不是静默失效，是成文的分工（见工作流 §9.3.2 末段）。
# §9.3.1「走势条件·加仓」，v3.02：已有持仓只须 `MA20 > MA60`，不要求 `收盘 > MA20`。
# 新建仓仍须 `收盘 > MA20 > MA60`。两者的差别只对**在手持仓**生效，故本脚本必须读持仓。
SEC93_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
BANK_RISK_PREMIUM = 0.02       # §12.31 股利折现的风险溢价


def is_bank(name: str) -> bool:
    return "银行" in name or name.endswith("行") or "农商" in name


# 与 `apply_model_bands_to_dossiers.py --min-available` 同一阈值：早于它的模型带视为时点过旧。
# v4.22（OI-068 统一口径）：陈旧带与模型判不可估的票在档案层判「无法估值」、在本层无 P/V
# ——两层同一结论：可见、不进 §9.3 任何判定。人工带只剩 §6.5.2.4 主体不可比一种（走覆盖表）。
MODEL_BAND_MIN_AVAILABLE = "2025-01-01"


def load_model_bands(path: Path, as_of: str) -> dict[str, dict]:
    """批量模型带，逐票取 `available_at ≤ as_of` 的最新一条。

    **不能按报告期排序取最新**——未到披露日的带在当日不可用，那是后视。
    """
    latest: dict[str, tuple[str, dict]] = {}
    stale: dict[str, tuple[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            status = row.get("status")
            if status not in (None, "", "ok"):
                continue
            avail = row.get("band_available_at") or row.get("available_at") or ""
            code = (row.get("security_code") or "").zfill(6)
            if len(avail) == 10 and avail <= as_of and code:
                if avail < MODEL_BAND_MIN_AVAILABLE:
                    if code not in stale or avail >= stale[code][0]:
                        stale[code] = (avail, str(row.get("security_name") or code))
                    continue
                if code not in latest or avail >= latest[code][0]:
                    latest[code] = (avail, row)
    dropped = {c: v for c, v in stale.items() if c not in latest}
    if dropped:
        print(f"  [陈旧带排除·OI-068] 模型带早于 {MODEL_BAND_MIN_AVAILABLE} 共 {len(dropped)} 只，"
              f"无 P/V 不进判定（档案层同判无法估值，§6.5.2.4 统一口径）："
              + "、".join(f"{n}({d})" for _, (d, n) in sorted(dropped.items())))
    return {code: row for code, (_, row) in latest.items()}


def bank_dividend_intrinsic(code: str, as_of: str, rf: float) -> float | None:
    """§12.31：`V = 近 12 个月每股现金分红 ÷ (十年国债 + 2%)`。无分红返回 None。"""
    total = 0.0
    low = f"{int(as_of[:4]) - 1}{as_of[4:]}"
    for path in sorted((ROOT / "data/raw/corporate_actions").glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if (row.get("security_code") or "").zfill(6) != code:
                    continue
                day = row.get("ex_dividend_date") or ""
                value = to_float(row.get("cash_per_share")) or 0.0
                if len(day) == 10 and low < day <= as_of and value > 0:
                    total += value
    return total / (rf + BANK_RISK_PREMIUM) if total > 0 else None


def daily_returns_window(codes: Iterable[str], window: int = 253) -> dict[str, list[float]]:
    """逐票近 `window` 根的日收益率，取自本地行情库。重叠不足 120 根的不参与相关性。"""
    out: dict[str, list[float]] = {}
    for code in codes:
        path = ROOT / "data/raw/ohlcv" / f"{code}.csv"
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as handle:
            closes = [float(r["close"]) for r in csv.DictReader(handle) if r.get("close")][-window:]
        if len(closes) >= 120:
            out[code] = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    return out


def pearson(returns: dict[str, list[float]], a: str, b: str) -> float:
    """两票日收益率的皮尔逊相关。任一缺数据返回 0——**当作不相关会放行**，故缺数据要单独报。"""
    xs, ys = returns.get(a), returns.get(b)
    if not xs or not ys:
        return 0.0
    n = min(len(xs), len(ys))
    xs, ys = xs[-n:], ys[-n:]
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((v - mx) ** 2 for v in xs))
    sy = math.sqrt(sum((v - my) ** 2 for v in ys))
    if sx == 0 or sy == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def attach_model_pv(rows: list[dict[str, object]], bands: dict[str, dict],
                    as_of: str, rf: float) -> None:
    """给每行挂上 §9.3 用的 `model_intrinsic_value` / `model_pv` / `model_band_source`。

    **与 §8 的 `fair_price_low/high`（逐票档案带）并存、互不覆盖**：档案带继续供
    §6.2 自动定档用，模型带只供 §9.3 用。"""
    for row in rows:
        code = str(row.get("security_code", "")).zfill(6)
        name = str(row.get("security_name", ""))
        intrinsic, source = None, ""
        if is_bank(name):
            intrinsic = bank_dividend_intrinsic(code, as_of, rf)
            if intrinsic:
                source = "股利折现"
        if intrinsic is None and code in bands:
            intrinsic = to_float(bands[code].get("intrinsic_value"))
            if intrinsic:
                source = f"模型带·{bands[code].get('report_date', '')}"
        close = to_float(row.get("close"))
        row["model_intrinsic_value"] = round(intrinsic, 4) if intrinsic else ""
        row["model_band_source"] = source
        row["model_pv"] = (round(close / intrinsic, 4)
                           if close and intrinsic and intrinsic > 0 else "")


def load_holdings() -> dict[str, float]:
    """{代码: 持股数}。读不到就返回空——**空 dict 会让本函数退回 v3.00 口径**，
    故调用方必须把「有没有读到持仓」显示出来，不能静默。"""
    out: dict[str, float] = {}
    if not SEC93_HOLDINGS.exists():
        return out
    with SEC93_HOLDINGS.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            shares = to_float(r.get("current_shares"))
            if shares and shares > 0:
                out[str(r["security_code"]).zfill(6)] = shares
    return out


def section97_entry_plan(rows: list[dict[str, object]], nav: float, funds: float | None = None,
                         holdings: dict[str, float] | None = None,
                         blocked: set[str] | None = None) -> dict[str, object]:
    """§9.3.2 第 3、5 步：按 `P/V` 升序、去相关、逐个买一档。

    §9.3.3 比例冷却：一手金额 > 一档时买一手，其后跳过 `round(x)−1` 次合格机会
    （本函数是单日快照，故只记 `cooldown_skips` 供次日跑批读，不在此处消费）。

    **两条与持仓有关的规则（v3.01/v3.02，OI-058／OI-059）**：
    - **走势条件分新旧**：新建仓须 `收盘 > MA20 > MA60`；**已有持仓的加仓只须 `MA20 > MA60`**。
    - **单票上限**：买入后该票市值 ÷ N 超过 `SEC93_POSITION_CAP` 即跳过、顺位补下一名；
      **只挡加仓，已有持仓因上涨越限不回削**。
    `holdings` 为空时两条都退化为原口径，故调用方须把「读到几只持仓」打出来。
    """
    holdings = holdings or {}
    tranche = nav * SEC93_TRANCHE_PCT

    def trend_ok(r) -> bool:
        c, m20, m60 = to_float(r.get("close")), to_float(r.get("ma20")), to_float(r.get("ma60"))
        if not (c and m20 and m60) or not m20 > m60:
            return False
        if str(r["security_code"]).zfill(6) in holdings:
            return True                      # 已持仓：只看均线排列
        return c > m20                       # 新建仓：还要站上 MA20

    def liquid_ok(r) -> bool:
        # §10.1 第 3 条：20 日均成交额低于 5,000 万元不列买入候选（v4.18 起在合格集硬执行；
        # 此前该门槛只存在于展示层，买入计划从未真正检查过它）。
        return (to_float(r.get("amount_ma20")) or 0.0) >= MIN_AMOUNT_MA20

    # §9.3.2 第 1 步：排除 review_pending（§7.5 冻结）。此前冻结只改展示字段、
    # 本函数不读它——冻结股照样进下扫序列（判例 2026-08-19：天山铝业冻结中仍参与排序，
    # 仅因相关性 0.72 被碰巧剔除）。「读起来在保护你、实际不保护任何东西」型，故在合格集处硬排除。
    blocked = blocked or set()
    frozen_out = [r for r in rows
                  if str(r["security_code"]).zfill(6) in blocked
                  and isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
                  and trend_ok(r)]
    illiquid_out = [r for r in rows
                    if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
                    and trend_ok(r) and not liquid_ok(r)
                    and str(r["security_code"]).zfill(6) not in blocked]
    eligible = [
        r for r in rows
        if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
        and trend_ok(r) and liquid_ok(r)
        and str(r["security_code"]).zfill(6) not in blocked
    ]
    eligible.sort(key=lambda r: r["model_pv"])
    n_cheap = sum(1 for r in rows
                  if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE)

    # **相关性基准必须含在手持仓**：§9.3.1 写的是「与**在手**/已选标的 ≤ 上限」，
    # 判例：2026-08-17 持有山西汾酒时，与之相关 0.79 的古井贡酒曾被排在买入计划第 1 位。
    held_rows = [r for r in rows if str(r["security_code"]).zfill(6) in holdings]
    returns = daily_returns_window(
        [str(r["security_code"]).zfill(6) for r in eligible]
        + [str(r["security_code"]).zfill(6) for r in held_rows])
    picked: list[dict] = []
    dropped: list[tuple[dict, float, str]] = []
    for cand in eligible[:SEC93_SCAN_DEPTH]:
        code = str(cand["security_code"]).zfill(6)
        worst, worst_name = 0.0, ""
        for held in held_rows + picked:
            if str(held["security_code"]).zfill(6) == code:
                continue                     # 加仓自身不与自己比
            value = pearson(returns, code, str(held["security_code"]).zfill(6))
            if value > worst:
                worst, worst_name = value, str(held.get("security_name", ""))
        if worst > SEC93_MAX_CORR:
            dropped.append((cand, worst, worst_name))
            continue
        picked.append(cand)

    # **可用资金 ≠ 净资产**（OI-062，2026-08-17 修）：满仓或带融资的账户里，净资产早已变成持仓市值，
    # 而买入只能用**现金＋未用授信**。
    cash, plan, capped = (nav if funds is None else max(funds, 0.0)), [], []
    for cand in picked:
        price = to_float(cand.get("close")) or 0.0
        if price <= 0:
            continue
        code = str(cand["security_code"]).zfill(6)
        lot_amount = price * SEC93_LOT
        lots = int(tranche // lot_amount) if lot_amount <= tranche else 1
        cooldown = 0 if lot_amount <= tranche else round(lot_amount / tranche) - 1
        amount = lots * lot_amount
        if lots <= 0 or amount > cash:
            continue
        # 单票上限：**按「买入后」的市值判**，与回测 `--position-cap` 逐字同义。
        held_value = holdings.get(code, 0.0) * price
        if SEC93_POSITION_CAP and nav > 0 and (held_value + amount) / nav > SEC93_POSITION_CAP:
            capped.append((cand, held_value / nav))
            continue
        cash -= amount
        plan.append({
            "trade_date": "",   # 由 report_section97 统一填信号日（OI-065：无日期列则文件无法自证时点）
            "security_code": str(cand["security_code"]).zfill(6),
            "security_name": cand.get("security_name", ""),
            "quality_tier": cand.get("quality_tier", ""),
            "close": price,
            "model_intrinsic_value": cand.get("model_intrinsic_value", ""),
            "model_pv": cand["model_pv"],
            "model_band_source": cand.get("model_band_source", ""),
            "lots": lots,
            "shares": lots * SEC93_LOT,
            "amount": round(amount, 2),
            "cooldown_skips": cooldown,
        })
    return {"plan": plan, "dropped": dropped, "eligible": eligible, "capped": capped,
            "frozen_out": frozen_out, "illiquid_out": illiquid_out,
            "n_cheap": n_cheap, "cash": cash, "tranche": tranche,
            "funds0": (nav if funds is None else max(funds, 0.0)), "funds_given": funds is not None,
            "n_held": len(holdings),
            "n_addon": sum(1 for r in eligible
                           if str(r["security_code"]).zfill(6) in holdings
                           and not (to_float(r.get("close")) or 0) > (to_float(r.get("ma20")) or 0))}


# `daily_entry_plan.csv` 的固定列。空计划也要写出带表头的空文件——OI-065：买入 0 只时
# 不写文件，旧计划就原样留在盘上冒充当日结论（判例 2026-08-18：文件内容还是 08-14 的四条买入）。
PLAN_FIELDS = ["trade_date", "security_code", "security_name", "quality_tier", "close",
               "model_intrinsic_value", "model_pv", "model_band_source",
               "lots", "shares", "amount", "cooldown_skips"]


def report_section97(result: dict[str, object], nav: float, out_path: Path,
                     as_of: str = "") -> None:
    plan, dropped = result["plan"], result["dropped"]
    for p in plan:
        p["trade_date"] = as_of
    invested = float(result["funds0"]) - result["cash"]
    print(f"\n§9.3 机械执行：`P/V ≤ {SEC93_BUY_LINE}` 的 {result['n_cheap']} 只；"
          f"再过走势条件的 **{len(result['eligible'])} 只**"
          f"（新建仓 `收>MA20>MA60`；**已持仓只须 `MA20>MA60`**，其中 {result['n_addon']} 只"
          f"是靠这条放宽进来的回踩加仓）；"
          f"流动性门槛（20日均额<{MIN_AMOUNT_MA20 / 1e8:.1f}亿）排除 {len(result.get('illiquid_out') or [])} 只；"
          f"§7.5 冻结硬排除 {len(result.get('frozen_out') or [])} 只；"
          f"相关性 >{SEC93_MAX_CORR} 剔除 {len(dropped)} 只 → 买入 {len(plan)} 只")
    for il in result.get("illiquid_out") or []:
        print(f"  [流动性排除·§10.1] {il.get('security_name','')} P/V {il['model_pv']:.2f}"
              f"｜20日均额 {(to_float(il.get('amount_ma20')) or 0.0) / 1e4:,.0f} 万")
    for fz in result.get("frozen_out") or []:
        print(f"  [冻结排除·review_pending] {fz.get('security_name','')} P/V {fz['model_pv']:.2f}"
              f"（两闸已开，待 §6.7 重建解冻后按当日名次重入）")
    if result["n_held"] == 0:
        print("  ⚠ **没读到任何持仓**（data/processed/a_share_holdings.csv 缺失或为空）"
              "——加仓放宽会退回旧口径，买入计划不可直接照做")
    else:
        cap_txt = f"单票上限 {SEC93_POSITION_CAP:.0%}（只挡加仓、不强制减持）" if SEC93_POSITION_CAP else "单票无上限（v4.04 退役）"
        print(f"  持仓 {result['n_held']} 只已载入｜{cap_txt}")
    for cand, w in result["capped"]:
        print(f"  [单票上限挡下] {cand.get('security_name','')} "
              f"P/V {cand['model_pv']:.2f}｜现持仓已占净资产 {w:.1%}，再买一档将越过 "
              f"{SEC93_POSITION_CAP:.0%}")
    if result["funds_given"]:
        print(f"  一档 {result['tranche'] / 1e4:,.2f} 万｜**可用资金 {float(result['funds0']) / 1e4:,.2f} 万**"
              f"（现金＋未用授信）→ 投入 {invested / 1e4:,.2f} 万（占净资产 {invested / nav * 100:.1f}%）"
              f"｜余 {result['cash'] / 1e4:,.2f} 万")
    else:
        print(f"  一档 {result['tranche'] / 1e4:,.2f} 万｜⚠ **未给 `--funds`，按「可用资金＝净资产」估算**"
              f"（OI-062：满仓/带融资账户上此计划资金上不可执行，买入须走 §9.3.2 换仓）"
              f"｜投入 {invested / 1e4:,.1f} 万（仓位 {invested / nav * 100:.1f}%）｜余 {result['cash'] / 1e4:,.1f} 万")
    for i, p in enumerate(plan, 1):
        band = f"{p['model_intrinsic_value'] * 0.9:.2f}-{p['model_intrinsic_value'] * 1.1:.2f}" \
            if isinstance(p["model_intrinsic_value"], float) else "—"
        print(f"  {i:>3} {p['security_code']} {p['security_name']:<9}"
              f"｜现价 {p['close']:>8.2f}｜带 {band:>17}｜P/V {p['model_pv']:.2f}"
              f"｜{p['shares']:>5} 股 {p['amount'] / 1e4:>5.2f} 万"
              + (f"｜其后跳过 {p['cooldown_skips']} 次" if p["cooldown_skips"] else ""))
    for cand, value, who in dropped:
        print(f"  [相关性剔除] {cand.get('security_name','')} "
              f"P/V {cand['model_pv']:.2f}｜与已选 {who} 相关 {value:.2f}")
    # OI-065：**空计划也必须落盘**（只含表头），否则前一日的旧计划会原样留在盘上冒充今日结论；
    # `trade_date` 列让读取方能自证文件时点，不再依赖 mtime。
    write_csv(out_path, plan, PLAN_FIELDS)
    print(f"  买入计划已写 {out_path}（trade_date={as_of or '—'}，{len(plan)} 条"
          + ("；**今日买入为空，已写空文件覆盖旧计划**）" if not plan else "）"))


FIELDNAMES = [
    "trade_date",
    "security_code",
    "security_name",
    "exchange",
    "quality_tier",
    "quality_tier_label",
    # 参考分（§5.7）：池 CSV 随行带进来，仅供报告显示同档内排序，不参与任何判定。
    "quality_score",
    "pool_layer",
    "valuation_tier",
    "valuation_tier_effective",
    "valuation_tier_changed",
    "fair_price_low",
    "fair_price_high",
    "band_position",
    "margin_of_safety",
    # §9.3 用的模型带三列。**与 fair_price_low/high 并存不混用**：
    # 前者是逐票档案带、供 §6.2 自动定档；这三列是批量模型带、供 §9.3 买入判定。
    "model_intrinsic_value",
    "model_band_source",
    "model_pv",
    "strategy_tag",
    "total_market_cap_bn",
    "signal_state",
    "review_frozen",
    "note",
    "gap_trading_days",
    "gap_return",
    "gap_max_vol_ratio",
    "gap_max_vol_day",
    "close",
    "high",
    "low",
    "pct_chg",
    "amount",
    "ma20",
    "ma60",
    "amount_ma20",
    "data_source",
    "screened_at_utc",
]


def main() -> int:
    args = parse_args()
    symbols = {item.strip().zfill(6) for item in args.symbols.split(",") if item.strip()} or None
    input_rows = load_csv(args.input)
    since = args.since
    if since == "auto":
        since = detect_last_scan(args.log_file, args.as_of)
        if since:
            print(f"§8.4 缺口回溯：检出上次扫描日 {since}，将回溯 {since}→{args.as_of} 区间")
        else:
            print("§8.4 缺口回溯：未检出上次扫描日，本次按单日快照执行")
    rows = scan(input_rows, args.as_of, symbols, args.timeout, args.workers, since)
    blocked = load_blocked_codes(args.review_queue)
    for row in rows:
        # §7.5 复核期买入冻结的可见性列；硬排除在 section97_entry_plan 内执行。
        row["review_frozen"] = bool(blocked) and str(row.get("security_code", "")).zfill(6) in (blocked or set())

    # §9.3 的 P/V **必须在落盘之前挂上**：`FIELDNAMES` 里已经声明了那三列，
    # 若等落盘后再算，写出去的就是三列空值。首版就踩过这一脚，靠落地校验（下方 priced 计数）当场发现。
    section97_ready = bool(args.model_bands and args.model_bands.exists())
    if section97_ready:
        bands = load_model_bands(args.model_bands, args.evidence_date or args.as_of)
        attach_model_pv(rows, bands, args.as_of, args.rf)
        priced = sum(1 for r in rows if isinstance(r.get("model_pv"), float))
        print(f"§9.3 模型带：{len(bands)} 只有带，{priced}/{len(rows)} 只算出 P/V"
              f"（银行走股利折现 rf={args.rf:.4%}+{BANK_RISK_PREMIUM:.0%}）")
        if priced < len(rows):
            missing = [str(r.get("security_name", "")) for r in rows
                       if not isinstance(r.get("model_pv"), float)][:8]
            print(f"  **无带 {len(rows) - priced} 只**（§9.3 判定不到它们）：{'、'.join(missing)}")
        if rows and not priced:
            print("  **告警：model_pv 整列为空** —— 模型带与池对不上号，§9.3 本次等于没跑")
    write_csv(args.output_csv, rows, FIELDNAMES)
    review_note = (
        "复核冻结：已启用（读取更新队列）。" if blocked is not None else
        "复核冻结：未启用（更新队列文件缺失，§7.5 冻结未生效）。"
    )
    log_scan_decisions(args.log_file, rows, args.as_of, args.input, args.output_csv)
    print(f"scanned {len(rows)} rows from {args.input}; {review_note}")

    # 落地校验：新增列跑完必须核对非空行数——「某列整体为空而无人察觉」是本仓库复发过四次的
    # 静默失效签名（§13 第 3 条），而报告一旦改用手填值就再也发现不了。
    scored = [r for r in rows if str(r.get("quality_score", "")).strip()]
    print(f"参考分（工作流 §5.7）非空 {len(scored)}/{len(rows)} 行")
    if rows and not scored:
        print("**告警：quality_score 整列为空** —— 池 CSV 未透传参考分，报告不得手填，先修池物化")

    # §9.3 的买入计划（`attach_model_pv` 已在落盘前跑过，见上文）。
    if section97_ready:
        if args.nav > 0:
            report_section97(section97_entry_plan(rows, args.nav, args.funds, load_holdings(),
                                                  blocked or set()),
                             args.nav, args.plan_out, args.as_of)
        else:
            print("§9.3 未给 --nav，只算 P/V 不出买入计划（一档以净资产为基数）")
    else:
        print(f"§9.3 机械执行层未运行：模型带文件不存在（{args.model_bands}）。"
              f"重建见 §6.7；不跑它则本次只产出 §8 的取数，**买入判定缺席**")

    return data_error_exit_code(rows)


DATA_ERROR_ABORT_RATIO = 0.5


def data_error_exit_code(rows: list[dict]) -> int:
    """行情整体取不到时必须非 0 退出（§13 第 3 条「静默失效」）。

    逐票 `except` 把取数失败降级为一行 `data_error` 是对的——一只票挂了不该中断整批。
    但把**每一票都失败**也当成成功就不对了：全市场接口宕机时脚本照样退出 0、照样写出
    一份完整 CSV，只是每行都是 data_error，下游与调度器都看不出今天其实没扫成。

    阈值取 50%：正常交易日的 data_error 是个位数（停牌/退市/代码变更），过半必是系统性故障。
    """
    if not rows:
        print("⚠️ 扫描 0 行——输入池为空或过滤条件把全部标的排除了", file=sys.stderr)
        return 2
    failed = [r for r in rows if r.get("signal_state") == "data_error"]
    ratio = len(failed) / len(rows)
    if ratio >= DATA_ERROR_ABORT_RATIO:
        sample = "; ".join(str(r.get("note", ""))[:80] for r in failed[:3])
        print(f"⚠️ {len(failed)}/{len(rows)} 行取数失败（{ratio:.0%} ≥ {DATA_ERROR_ABORT_RATIO:.0%}）"
              f"——判定为系统性行情故障，本次扫描结果不可用。样例：{sample}", file=sys.stderr)
        return 1
    if failed:
        print(f"注意：{len(failed)}/{len(rows)} 行取数失败（低于 {DATA_ERROR_ABORT_RATIO:.0%} 阈值，按个别停牌处理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
