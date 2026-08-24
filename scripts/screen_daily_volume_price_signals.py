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
import re
import math
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from a_share_quotes import quote_symbol
from build_a_share_core_valuation_pool import effective_valuation_tier
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log
from pv_ratio import trading_pv  # noqa: E402  v4.62 OI-091：P/V 唯一实现


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from divspread_names import is_divspread_financial  # noqa: E402  v4.56 银行＋保险股利折现判定
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
    """东财 push2 secid：沪市 `1.`，深市与北交所 `0.`（与 `fetch_a_share_valuation_evidence.secid` 同口径）。
    东财历史K线端点不服务北交所——日线一律经 `fetch_daily_rows` 取，北交所在那里改道腾讯，
    不得拿本函数的返回值直连东财K线端点查北交所代码。"""
    code = code.zfill(6)
    exchange = (exchange or "").upper()
    if exchange == "SSE" or code.startswith(("60", "68", "69")):
        return f"1.{code}"
    return f"0.{code}"


def get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "ignore"))


def fetch_daily_rows(code: str, exchange: str, as_of: str, timeout: float, fq: str = "qfq") -> tuple[str, list[dict[str, float | str]]]:
    """A 股日线**唯一取数实现**（OI-095：扫描器与 `track_holdings_daily` 同用本函数，两侧 MA60 同源同基）。
    东财主源、腾讯备源，北交所直接走腾讯。`fq="qfq"`（缺省）前复权（§8.3 均线/走势口径）；
    `fq=""` 不复权（跟踪器取当日收盘用）。"""
    query = urllib.parse.urlencode(
        {
            "secid": infer_secid(code, exchange),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "1" if fq else "0",
            "beg": "20200101",
            "end": as_of.replace("-", ""),
            "lmt": "1000",
        }
    )
    # 北交所（92/43/83/87 前缀）：东财K线无数据，直接走腾讯 newfqkline。
    if quote_symbol(code, exchange).startswith("bj"):
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout, fq)
    url = f"{EASTMONEY_KLINE}?{query}"
    try:
        payload = get_json(url, timeout)
    except OSError:
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout, fq)
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return fetch_daily_rows_tencent(code, exchange, as_of, timeout, fq)
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


def fetch_daily_rows_tencent(code: str, exchange: str, as_of: str, timeout: float, fq: str = "qfq") -> tuple[str, list[dict[str, float | str]]]:
    """后备源：腾讯日线（北交所主源，走 newfqkline）。`fq` 语义同 `fetch_daily_rows`（"" = 不复权）。
    成交量单位为手（口径内部一致）；成交额接口未提供，以收盘价×成交量×100近似，只影响流动性门槛的估计。"""
    symbol = quote_symbol(code, exchange)
    base = TENCENT_KLINE
    param = f"{symbol},day,2020-01-01,{as_of},1000,{fq}"
    url = f"{base}?param={param}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    data = (payload.get("data") or {}).get(symbol) or {}
    klines = [list(parts) for parts in ((data.get("qfqday") or data.get("day")) if fq else data.get("day")) or []]
    # 腾讯前复权序列可能滞后一个交易日：用不复权序列补齐最新K线（不复权序列自身无此滞后）。
    # 成交量单位沪深口径不一（股/手），按重叠日成交量比例归一后再拼接。
    if fq and klines and str(klines[-1][0]) < as_of:
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
        # §9.3.1 相关性的同源K线（OI-093）：多留一根算首日收益率。线程间各写各的代码键，无竞态。
        CLOSE_SERIES[code] = [(str(r["date"]), float(r["close"]))
                              for r in price_rows[-(CORR_WINDOW + 2):] if to_float(r.get("close"))]
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


def detect_last_scan(prior_csv: Path, as_of: str) -> str:
    """§8.4：自动检出上一次扫描日——缺口回溯不能依赖人记得传 --since。

    读上一份扫描产物（`daily_buy_candidates.csv`）的 `trade_date`（OI-096：决策日志不再逐股写
    `decision_result=ok` 行，不能再从日志检出）。产物在本次扫描落盘前读取，存的是上一次的日期；
    同日重跑或补跑更早日期时取不到 `< as_of` 的日期，按单日快照执行。"""
    if not prior_csv.exists():
        return ""
    dates = set()
    with prior_csv.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = str(row.get("trade_date") or "").strip()
            if len(day) == 10:
                dates.add(day)
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
        # §2 审计口径（OI-096）：只记结论行——取数异常（data_error/insufficient_price_history）
        # 与 §7.5 复核冻结；正常行情行不再逐股写 `decision_result=ok`（上次扫描日由
        # detect_last_scan 读扫描产物的 trade_date，买入结论的唯一真值是 daily_entry_plan.csv，
        # 持仓动作由 track_holdings_daily 记）。
        state = str(row.get("signal_state") or "")
        frozen = bool(row.get("review_frozen"))
        if state == "ok" and not frozen:
            continue
        reason = str(row.get("note") or "")
        if frozen:
            reason = (reason + "；" if reason else "") + "§7.5 复核期买入冻结"
        entries.append(
            {
                "logged_at_utc": logged_at,
                "workflow_stage": "daily_volume_price_scan",
                "run_id": f"daily_volume_price_scan:{as_of}",
                "as_of": as_of,
                "security_code": row.get("security_code", ""),
                "security_name": row.get("security_name", ""),
                "decision_type": "daily_signal_state",
                "decision_result": "review_frozen" if state == "ok" else state,
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
    parser.add_argument("--rf", type=float, default=_default_rf(),
                        help="十年国债收益率，银行股利折现用（§6.5.1 第 4 条）；"
                             "缺省取 data/reference/cost_of_equity_inputs.csv 最新一行，与 rebuild_bank_bands 同源")
    parser.add_argument("--plan-out", type=Path, default=DEFAULT_PLAN_OUT)
    return parser.parse_args()


def load_tactical_gate_codes(path: Path | None = None) -> set[str]:
    """§9.3.1 L3 战术闸门（v4.53）：分层表中 quality_tier=L3 且 tactical_thesis 为空或以「无／暂无／不可买」开头的代码。
    rubric §8 把 tactical_thesis 定为「L3 买入前置」，v4.18 删矩阵后一直无人读取（OI-084）；现按用户裁定①在合格集硬排除。"""
    path = path or SEC93_TIERS
    if not SEC93_L3_TACTICAL_GATE or not path.exists():
        return set()
    out: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if (row.get("quality_tier") or "").strip() != "L3":
                continue
            thesis = (row.get("tactical_thesis") or "").strip()
            if not thesis or SEC93_TACTICAL_NONE.match(thesis):
                out.add(row["security_code"].zfill(6))
    return out


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
SEC93_BUY_LINE = 0.9343        # §9.3.1 买入线（v4.62：季度当期化纪元对齐解、保留四位小数，用户裁定「三线按对齐解」；合格面 17.622%，回测日志 §12.120；v4.61 为 0.9505、v4.34 为 0.9434）
SEC93_MAX_CORR = 0.70          # §9.3.1，252 日日收益率皮尔逊相关上限
SEC93_SCAN_DEPTH = 40          # §9.3.2 第 3 步：相关性过滤时最多下扫多少名
SEC93_TRANCHE_PCT = 0.05       # §9.3.1 单次买入比例
SEC93_LOT = 100                # A 股一手
SEC93_POSITION_CAP = 0.60      # §9.3.1「单票机械上限」（v4.64，用户 2026-08-23 裁定 60%；回测日志 §12.123）：
                               # 持仓市值 ÷ 当日净资产 N ≥ 60% 不再加仓，不足时本档只补到 60%（可小于一档、按手向下取整）；
                               # **只挡加仓、不触发任何卖出**，上涨越限不回削；新建仓与换仓目标（必为未持仓票）不受影响。
                               # None = 不设限（v4.04~v4.63 旧口径，§12.75）。与回测 `--position-cap` 同语义。
SEC93_SELL_LINE = 2.4671       # §9.3.1「减持线」，v4.62 季度当期化纪元对齐解（上侧面 30.858%；v4.61 为 2.5263、v4.34 为 2.5008）：P/V ≥ 线且收盘 < MA20 → 减一档。
SEC93_L3_TACTICAL_GATE = True   # §9.3.1「L3 战术闸门」（v4.53，OI-084 用户裁定①）：L3 且分层表 tactical_thesis 为空或判「无」者不进合格集（新建仓与加仓同）
SEC93_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
SEC93_TACTICAL_NONE = re.compile(r"^\W*(无|暂无|不可买)")   # 判「无战术理由」的写法
SEC93_GAIN_SELL = 1.25         # §9.3.1「涨幅减持」（v4.44 用户采纳，回测日志 §12.110/§12.113）：收盘较持仓均价涨幅 ≥ 125%（收盘 ≥ 均价×2.25）
                               # 且收盘 < MA20 → 减一档；资金不足时该类持仓优先作换仓卖出源（涨幅最大者先）。持仓均价 = 买入按股数加权、
                               # 减持不变、除权按 §11.4 折算（持仓表 cost_basis）。回测落点 `--gain-sell 1.25`（gated）。
# ↑ 本脚本只做买入侧（§9.3.2 第 4 步卖出是人工），该常量是减持线数值的**脚本侧唯一落点**，
#   供卖出侧人工核对引用——不是静默失效，是成文的分工（见工作流 §9.3.2 末段）。
# §9.3.1「走势条件·加仓」，v3.02：已有持仓只须 `MA20 > MA60`，不要求 `收盘 > MA20`。
# 新建仓仍须 `收盘 > MA20 > MA60`。两者的差别只对**在手持仓**生效，故本脚本必须读持仓。
SEC93_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
def _default_rf() -> float:
    """十年国债收益率缺省：data/reference/cost_of_equity_inputs.csv 最新一行；读不到退最后手抄值。"""
    try:
        with (ROOT / "data/reference/cost_of_equity_inputs.csv").open(encoding="utf-8") as fh:
            rows = [r for r in csv.reader(fh) if r and r[0][:2] == "20"]
        return float(rows[-1][1])
    except (OSError, ValueError, IndexError):
        return 0.017114


BANK_RISK_PREMIUM = 0.02       # §12.31 股利折现的风险溢价


def is_bank(name: str, code: str = "") -> bool:
    """银行与保险走股利折现（v4.56 起含保险，OI-085 用户裁定①；判定统一在 divspread_names）。"""
    return is_divspread_financial(code, name)


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


@lru_cache(maxsize=1)
def _dividend_distributions() -> dict[str, list]:
    from divspread_dividend import load_distributions
    return load_distributions()


def bank_dividend_intrinsic(code: str, as_of: str, rf: float) -> float | None:
    """§12.31：`V = 最近已知完整财年每股现金分红 ÷ (十年国债 + 2%)`（分子口径 `divspread_dividend`，
    与 `rebuild_bank_bands.py` 历史逐日同一实现）。无分红返回 None。"""
    from divspread_dividend import annual_dividend, dividend_value
    got = annual_dividend(_dividend_distributions().get(code.zfill(6), []), as_of)
    return dividend_value(got[0], rf, BANK_RISK_PREMIUM) if got else None


# §9.3.1 相关性的数据源（OI-093）：扫描当日逐票已取的前复权K线（`scan_one` 落入本表），
# 两侧同源、窗口末端即信号日。此前读 `data/raw/ohlcv/` 行情库——该库按需增量、不随 §8 刷新，
# 窗口末端可落后信号日数周，且缺文件时 pearson 按 0 相关静默放行。
CLOSE_SERIES: dict[str, list[tuple[str, float]]] = {}
CORR_WINDOW = 252          # §9.3.1：近 252 日日收益率
CORR_MIN_OVERLAP = 120     # 与回测 Correlations 同阈：重叠收益率不足此数 → 无值（不当作 0）


def corr_252(a: str, b: str) -> float | None:
    """两票近 252 日日收益率的皮尔逊相关，按交易日对齐（停牌日不同则取交集）。

    数据缺失或重叠不足 `CORR_MIN_OVERLAP` 返回 **None＝未知**，交调用方显式列名单——
    与回测 `Correlations.get` 同语义，不再把缺数据当 0 相关放行。"""
    sa, sb = CLOSE_SERIES.get(a), CLOSE_SERIES.get(b)
    if not sa or not sb:
        return None
    ra = {d: c / p - 1 for (_, p), (d, c) in zip(sa, sa[1:]) if p > 0}
    rb = {d: c / p - 1 for (_, p), (d, c) in zip(sb, sb[1:]) if p > 0}
    common = sorted(ra.keys() & rb.keys())[-CORR_WINDOW:]
    if len(common) < CORR_MIN_OVERLAP:
        return None
    xs = [ra[d] for d in common]
    ys = [rb[d] for d in common]
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
        if is_bank(name, code):
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
        # v4.62（OI-091）：P/V 走 `pv_ratio.trading_pv`——ROIC 路径为 (现价+每股净负债)÷每股企业价值，其余 现价÷V
        if close and intrinsic and intrinsic > 0:
            if source.startswith("模型带") and code in bands:
                pv_value = trading_pv(close, bands[code])
            else:
                pv_value = close / intrinsic
            row["model_pv"] = round(pv_value, 4) if pv_value is not None else ""
        else:
            row["model_pv"] = ""


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


def section93_entry_plan(rows: list[dict[str, object]], nav: float, funds: float | None = None,
                         holdings: dict[str, float] | None = None,
                         blocked: set[str] | None = None,
                         tactical_gated: set[str] | None = None) -> dict[str, object]:
    """§9.3.2 第 3、5 步：按 `P/V` 升序、去相关、逐个买一档。

    §9.3.3 比例冷却：一手金额 > 一档时买一手，其后跳过 `round(x)−1` 次合格机会
    （本函数是单日快照，故只记 `cooldown_skips` 供次日跑批读，不在此处消费）。

    **两条与持仓有关的规则（v3.01/v3.02，OI-058／OI-059）**：
    - **走势条件分新旧**：新建仓须 `收盘 > MA20 > MA60`；**已有持仓的加仓只须 `MA20 > MA60`**。
    - **单票上限**（v4.64 = 60%）：现持仓市值 ÷ N ≥ 上限即跳过、顺位补下一名；不足时本档只补到上限；
      **只挡加仓，不触发卖出，已有持仓因上涨越限不回削**。
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
    # §9.3.1 L3 战术闸门（v4.53）：L3 无战术理由不进合格集（新建仓与加仓同），与冻结同为硬排除。
    tactical_gated = tactical_gated or set()
    tactical_out = [r for r in rows
                    if str(r["security_code"]).zfill(6) in tactical_gated
                    and isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
                    and trend_ok(r) and liquid_ok(r)
                    and str(r["security_code"]).zfill(6) not in blocked]
    eligible = [
        r for r in rows
        if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
        and trend_ok(r) and liquid_ok(r)
        and str(r["security_code"]).zfill(6) not in blocked
        and str(r["security_code"]).zfill(6) not in tactical_gated
    ]
    eligible.sort(key=lambda r: r["model_pv"])
    n_cheap = sum(1 for r in rows
                  if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE)

    # **相关性基准必须含在手持仓**：§9.3.1 写的是「与**在手**/已选标的 ≤ 上限」，
    # 判例：2026-08-17 持有山西汾酒时，与之相关 0.79 的古井贡酒曾被排在买入计划第 1 位。
    held_rows = [r for r in rows if str(r["security_code"]).zfill(6) in holdings]
    picked: list[dict] = []
    dropped: list[tuple[dict, float, str]] = []
    corr_unknown: list[tuple[dict, str]] = []    # OI-093：算不出相关性的候选与对手名单，放行但显式列出
    for cand in eligible[:SEC93_SCAN_DEPTH]:
        code = str(cand["security_code"]).zfill(6)
        worst, worst_name = 0.0, ""
        unknown: list[str] = []
        for held in held_rows + picked:
            other = str(held["security_code"]).zfill(6)
            if other == code:
                continue                     # 加仓自身不与自己比
            value = corr_252(code, other)
            if value is None:                # 未知 ≠ 不相关：与回测同语义放行，但必须报出来
                unknown.append(str(held.get("security_name", "")) or other)
                continue
            if value > worst:
                worst, worst_name = value, str(held.get("security_name", ""))
        if worst > SEC93_MAX_CORR:
            dropped.append((cand, worst, worst_name))
            continue
        if unknown:
            # 同一持仓可能既在 held_rows 又已入 picked（加仓行），名单去重
            corr_unknown.append((cand, "、".join(dict.fromkeys(unknown))))
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
        if lot_amount <= tranche:
            budget, cooldown = tranche, 0
        else:                                   # 高价股：一档买不起一手 → 买一手、比例冷却（§9.3.3）
            budget, cooldown = lot_amount, round(lot_amount / tranche) - 1
        # **可用资金不足一档 → 买到用尽**（v4.64 对齐回测 `amount = min(一档, 可用资金)`；此前扫描器
        # 遇「一档 > 可用」整笔跳过，与回测不同步——按 §9.3.1「资金用尽即停」与 §9.3.1.2 同步原则改正）。
        budget = min(budget, cash)
        # 单票上限（v4.64）：与回测 `--position-cap` 同语义——`room = N × 上限 − 现持仓市值`，
        # room ≤ 0 跳过；room 不足一档时本档只补到上限。**只挡加仓**：已有持仓因上涨越限不回削；
        # 新建仓 held_value = 0、一档 5% 远低于上限，不受影响。
        held_value = holdings.get(code, 0.0) * price
        room = None
        if SEC93_POSITION_CAP and nav > 0:
            room = nav * SEC93_POSITION_CAP - held_value
            if room <= 0:
                capped.append((cand, held_value / nav))
                continue
            budget = min(budget, room)
        lots = int(budget // lot_amount)          # 按一手向下取整，不为迁就整手提高档位（§9.3.1.1）
        if lots <= 0:
            if room is not None and room < lot_amount:
                capped.append((cand, held_value / nav))
            continue
        amount = lots * lot_amount
        cash -= amount
        plan.append({
            "trade_date": "",   # 由 report_section93 统一填信号日（OI-065：无日期列则文件无法自证时点）
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
    return {"plan": plan, "dropped": dropped, "corr_unknown": corr_unknown,
            "eligible": eligible, "capped": capped,
            "frozen_out": frozen_out, "illiquid_out": illiquid_out, "tactical_out": tactical_out,
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


def report_section93(result: dict[str, object], nav: float, out_path: Path,
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
          f"L3 战术闸门排除 {len(result.get('tactical_out') or [])} 只；"
          f"相关性 >{SEC93_MAX_CORR} 剔除 {len(dropped)} 只 → 买入 {len(plan)} 只")
    for il in result.get("illiquid_out") or []:
        print(f"  [流动性排除·§10.1] {il.get('security_name','')} P/V {il['model_pv']:.2f}"
              f"｜20日均额 {(to_float(il.get('amount_ma20')) or 0.0) / 1e4:,.0f} 万")
    for tg in result.get("tactical_out") or []:
        print(f"  [L3 战术闸门排除·§9.3.1] {tg.get('security_name','')} P/V {tg['model_pv']:.2f}"
              f"（分层表 tactical_thesis 为空或判「无」；补判为条件式战术理由后按当日名次重入）")
    for fz in result.get("frozen_out") or []:
        print(f"  [冻结排除·review_pending] {fz.get('security_name','')} P/V {fz['model_pv']:.2f}"
              f"（两闸已开，待 §6.7 重建解冻后按当日名次重入）")
    if result["n_held"] == 0:
        print("  ⚠ **没读到任何持仓**（data/processed/a_share_holdings.csv 缺失或为空）"
              "——加仓放宽会退回旧口径，买入计划不可直接照做")
    else:
        cap_txt = f"单票上限 {SEC93_POSITION_CAP:.0%}（只挡加仓、不触发卖出；v4.64）" if SEC93_POSITION_CAP else "单票无上限"
        print(f"  持仓 {result['n_held']} 只已载入｜{cap_txt}")
    for cand, w in result["capped"]:
        print(f"  [单票上限挡下] {cand.get('security_name','')} "
              f"P/V {cand['model_pv']:.2f}｜现持仓已占净资产 {w:.1%}，已达/不足一手可补至 "
              f"{SEC93_POSITION_CAP:.0%} 上限，不加仓")
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
    for cand, who in result.get("corr_unknown") or []:
        print(f"  [相关性缺数据·OI-093] {cand.get('security_name','')} "
              f"P/V {cand['model_pv']:.2f}｜与 {who} 的重叠K线不足 {CORR_MIN_OVERLAP} 根，"
              f"按未知放行（与回测同语义），如需人工核对相关性再执行")
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
        since = detect_last_scan(args.output_csv, args.as_of)
        if since:
            print(f"§8.4 缺口回溯：检出上次扫描日 {since}，将回溯 {since}→{args.as_of} 区间")
        else:
            print("§8.4 缺口回溯：未检出上次扫描日，本次按单日快照执行")
    rows = scan(input_rows, args.as_of, symbols, args.timeout, args.workers, since)
    blocked = load_blocked_codes(args.review_queue)
    for row in rows:
        # §7.5 复核期买入冻结的可见性列；硬排除在 section93_entry_plan 内执行。
        row["review_frozen"] = bool(blocked) and str(row.get("security_code", "")).zfill(6) in (blocked or set())

    # §9.3 的 P/V **必须在落盘之前挂上**：`FIELDNAMES` 里已经声明了那三列，
    # 若等落盘后再算，写出去的就是三列空值。首版就踩过这一脚，靠落地校验（下方 priced 计数）当场发现。
    section93_ready = bool(args.model_bands and args.model_bands.exists())
    if section93_ready:
        bands = load_model_bands(args.model_bands, args.evidence_date or args.as_of)
        attach_model_pv(rows, bands, args.as_of, args.rf)
        priced = sum(1 for r in rows if isinstance(r.get("model_pv"), float))
        print(f"§9.3 模型带：{len(bands)} 只有带，{priced}/{len(rows)} 只算出 P/V"
              f"（银行与保险走股利折现 rf={args.rf:.4%}+{BANK_RISK_PREMIUM:.0%}）")
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
    if section93_ready:
        if args.nav > 0:
            report_section93(section93_entry_plan(rows, args.nav, args.funds, load_holdings(),
                                                  blocked or set(), load_tactical_gate_codes()),
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
