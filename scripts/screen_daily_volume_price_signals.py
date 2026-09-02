#!/usr/bin/env python3
"""每日行情取数（工作流 §8）＋ §9.3 机械执行层。

v4.18 起本脚本只做判定所需的事：取收盘/MA20/MA60/成交额、算 `P/V`、
§7.5 冻结排除、§9.3.2 先卖后买（卖出清单 `daily_sell_plan.csv`：止损复核／涨幅减持／出名单／换仓／
余仓清空；买入计划 `daily_entry_plan.csv`）、§9.3.3 比例冷却计数器（`daily_cooldown_state.csv`，买入侧与卖出侧各自计数）、
§8.4 缺口回溯（只报区间涨跌与放量峰值）。持仓不在核心池内的票另取行情、只进卖出侧。
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
from a_share_signal_dates import evidence_iso_for_signal
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log
from pv_ratio import trading_pv  # noqa: E402  v4.62 OI-091：P/V 唯一实现


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from divspread_names import is_divspread_financial  # noqa: E402  v4.56 银行＋保险股利折现判定
DEFAULT_INPUT = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_buy_candidates.csv"
DEFAULT_REVIEW_QUEUE = ROOT / "data/interim/a_share_report_update_queue.csv"
DEFAULT_MODEL_BANDS = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
# v4.92 SPA：持仓侧带（逐票取候选侧与 B2 较高 V，`build_hold_model_bands.py`）——§9.3.1 换仓来源读它
DEFAULT_HOLD_BANDS = ROOT / "data/processed/a_share_pool_model_bands_hold.csv"
DEFAULT_PLAN_OUT = ROOT / "data/processed/daily_entry_plan.csv"
DEFAULT_SELL_PLAN_OUT = ROOT / "data/processed/daily_sell_plan.csv"
SECURITIES_MASTER = ROOT / "data/raw/a_share_securities.csv"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 后备行情源：东财历史行情不可用/空响应时切换（同为前复权日线；成交额以收盘×量近似，只进展示列 `amount`／`amount_ma20`，不进判定）。
# 统一走腾讯 newfqkline：同构覆盖 sh/sz/bj，且为北交所唯一可用历史K线源；旧 web.ifzq 端点在批量扫描下易限流（2026-07-17 实测 501）。
TENCENT_KLINE = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"



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
    成交量单位为手（口径内部一致）；成交额接口未提供，以收盘价×成交量×100近似，只进展示列、不进判定。"""
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

    # 带内位置：现价相对合理价区间的落点（展示列，不进任何判定）。
    close = to_float(snapshot.get("close"))
    fair_low = to_float(pool_row.get("fair_price_low"))
    fair_high = to_float(pool_row.get("fair_price_high"))
    band_position = ""
    if close and fair_low and fair_high:
        if close > fair_high:
            band_position = f"越带顶+{(close / fair_high - 1) * 100:.0f}%"
        elif close < fair_low:
            band_position = f"低于带底-{(1 - close / fair_low) * 100:.0f}%"
        else:
            pos = (close - fair_low) / (fair_high - fair_low) * 100 if fair_high > fair_low else 0.0
            band_position = f"带内{pos:.0f}%"
    snapshot["band_position"] = band_position
    # 空间（区间中值 ÷ 现价 − 1）：只在现价低于带底时展示。
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
    parser.add_argument("--hold-bands", type=Path, default=DEFAULT_HOLD_BANDS,
                        help="持仓侧模型带表（§6.7 第 4 步逐票取候选侧与 B2 较高 V）；§9.3.1 换仓来源的 P/V 读它，"
                             "买入线与候选排序仍读 --model-bands；文件缺失时持仓侧退回候选侧并显著告警")
    parser.add_argument("--nav", type=float, default=0.0,
                        help="当日净资产，用于定一档 = NAV × §9.3.1 的比例。不给则只算 P/V、不出买入计划")
    parser.add_argument("--funds", type=float, default=None,
                        help="当日**可用资金 = 现金 + 未用授信**（OI-062）。买入计划以此为预算；"
                             "不给则退回「可用资金＝净资产」的旧估算并显著告警。满仓/带融资账户必须给。")
    parser.add_argument("--rf", type=float, default=_default_rf(),
                        help="十年国债收益率，银行股利折现用（§6.5.1 第 4 条）；"
                             "缺省取 data/reference/cost_of_equity_inputs.csv 最新一行，与 rebuild_bank_bands 同源")
    parser.add_argument("--plan-out", type=Path, default=DEFAULT_PLAN_OUT)
    parser.add_argument("--sell-out", type=Path, default=DEFAULT_SELL_PLAN_OUT,
                        help="§9.3.2 第 4 步卖出清单落点（止损复核／涨幅减持／出名单／换仓）")
    parser.add_argument("--cooldown-state", type=Path, default=DEFAULT_COOLDOWN_STATE,
                        help="§9.3.3 比例冷却计数器（买入、涨幅减持、换仓共用）；扫描器每日读写")
    parser.add_argument("--holdings", type=Path, default=SEC93_HOLDINGS)
    parser.add_argument("--triage", type=Path, default=SEC93_TRIAGE,
                        help="三类表：持仓不在 worth_attention 者按 §9.3.2 第 4 步每日减一档")
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
SEC93_BUY_LINE = 1.0454        # §9.3.1 买入线（对齐解、保留四位小数；下侧合格面 17.771%，回测日志 §12.170）
SEC93_MAX_CORR = 1.0           # §9.3.1：252 日相关性只计算并列报告、不作过滤（1.0 = 无一被跳过；与回测 `--max-corr` 同值）
SEC93_SCAN_DEPTH = 40          # 每日最多考察的合格候选名次（与回测 `--scan-depth` 同值；相关性不过滤后不绑定）
SEC93_TRANCHE_PCT = 0.05       # §9.3.1 单次买入比例
SEC93_LOT = 100                # A 股一手
SEC93_POSITION_CAP = 0.60      # §9.3.1「单票机械上限」（v4.64，用户 2026-08-23 裁定 60%；回测日志 §12.123）：
                               # 持仓市值 ÷ 当日净资产 N ≥ 60% 不再加仓，不足时本档只补到 60%（可小于一档、按手向下取整）；
                               # **只挡加仓、不触发任何卖出**，上涨越限不回削；新建仓与换仓目标（必为未持仓票）不受影响。
                               # None = 不设限（v4.04~v4.63 旧口径，§12.75）。与回测 `--position-cap` 同语义。
SEC93_L3_TACTICAL_GATE = True   # §9.3.1「L3 战术闸门」（v4.53，OI-084 用户裁定①）：L3 且分层表 tactical_thesis 为空或判「无」者不进合格集（新建仓与加仓同）
SEC93_TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
SEC93_TACTICAL_NONE = re.compile(r"^\W*(无|暂无|不可买)")   # 判「无战术理由」的写法
SEC93_GAIN_SELL = 1.10         # §9.3.1「涨幅减持」：收盘较持仓均价涨幅 ≥ 110%（收盘 ≥ 均价×2.10）→ 减一档，不看走势；
                               # 资金不足时该类持仓优先作换仓卖出源（涨幅最大者先，同样不要求弱势）。持仓均价 = 买入按股数加权、
                               # 减持不变、除权按 §11.4 折算（持仓表 cost_basis）。回测落点 `--gain-sell 1.10 --gain-sell-mode ungated`。
SEC93_SWAP_MARGIN = 0.16       # §9.3.1「换仓」：候选 P/V 须比被换出持仓低至少此差值（与回测 `--swap-margin` 同值）
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


@lru_cache(maxsize=1)
def _corporate_actions() -> dict[str, list]:
    from build_historical_valuation_bands import load_actions
    return load_actions()


def bank_dividend_intrinsic(code: str, as_of: str, rf: float) -> float | None:
    """§12.31：`V = 最近已知完整财年每股现金分红 ÷ (十年国债 + 2%)`（分子口径 `divspread_dividend`，
    与 `rebuild_bank_bands.py` 历史逐日同一实现）。无分红返回 None。

    OI-131：分子是该财年**实付**每股现金分红，故自其可得日起的送转与除息都要按交易所除权参考价
    折算 `v → (v − 现金红利) ÷ (1 + 送转比)`——不折则除息日股价下跳而 V 不动，`P/V` 凭空下跳一次
    股息率。锚与除权实现均与 `rebuild_bank_bands.py` 同源。"""
    from divspread_dividend import annual_dividend, annual_dividend_since, dividend_value
    from build_historical_valuation_bands import exright_adjust
    dists = _dividend_distributions().get(code.zfill(6), [])
    got = annual_dividend(dists, as_of)
    if not got:
        return None
    value = dividend_value(got[0], rf, BANK_RISK_PREMIUM)
    since = annual_dividend_since(dists, as_of)
    if value is None or not since:
        return value
    (adjusted,), _factor, _cash = exright_adjust(
        _corporate_actions().get(code.zfill(6), []), since, as_of, (value,), split_since=since)
    return adjusted if adjusted > 0 else None


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
                    as_of: str, rf: float, prefix: str = "model") -> None:
    """给每行挂上 §9.3 用的 `{prefix}_intrinsic_value` / `{prefix}_pv` / `{prefix}_band_source`。

    `prefix="model"` 为候选侧（买入线、候选排序），`prefix="hold"` 为持仓侧（v4.92 SPA：换仓来源）。
    **与 §8 的 `fair_price_low/high`（逐票档案带）并存、互不覆盖**：档案带只作展示，
    模型带只供 §9.3 用。"""
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
        row[f"{prefix}_intrinsic_value"] = round(intrinsic, 4) if intrinsic else ""
        row[f"{prefix}_band_source"] = source
        # v4.62（OI-091）：P/V 走 `pv_ratio.trading_pv`——ROIC 路径为 (现价+每股净负债)÷每股企业价值，其余 现价÷V
        if close and intrinsic and intrinsic > 0:
            if source.startswith("模型带") and code in bands:
                pv_value = trading_pv(close, bands[code])
            else:
                pv_value = close / intrinsic
            row[f"{prefix}_pv"] = round(pv_value, 4) if pv_value is not None else ""
        else:
            row[f"{prefix}_pv"] = ""


def load_holdings() -> dict[str, float]:
    """{代码: 持股数}。读不到就返回空——**空 dict 会让本函数退回 v3.00 口径**，
    故调用方必须把「有没有读到持仓」显示出来，不能静默。"""
    return {code: float(h["shares"]) for code, h in load_holdings_detail().items()}


def load_holdings_detail(path: Path | None = None) -> dict[str, dict[str, object]]:
    """§11.2 五列持仓表 → {代码: {name, shares, cost, stop}}；`cost`／`stop` 缺失为 None。"""
    path = path or SEC93_HOLDINGS
    out: dict[str, dict[str, object]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            shares = to_float(r.get("current_shares"))
            if shares and shares > 0:
                out[str(r["security_code"]).zfill(6)] = {
                    "name": r.get("security_name", ""), "shares": shares,
                    "cost": to_float(r.get("cost_basis")), "stop": to_float(r.get("entry_stop_price")),
                }
    return out


SEC93_TRIAGE = ROOT / "data/processed/a_share_attention_triage.csv"


def load_worth_attention_codes(path: Path | None = None) -> set[str] | None:
    """§9.3.2 第 4 步「已移出 worth_attention」的判据来源：三类表。文件缺失返回 None（不判出名单）。"""
    path = path or SEC93_TRIAGE
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {str(r["security_code"]).zfill(6) for r in csv.DictReader(fh)
                if (r.get("attention_class") or "").strip() == "worth_attention"}


def load_exchange_map(path: Path | None = None) -> dict[str, str]:
    """证券名单 {代码: 交易所}，供池外持仓取行情时定 secid。"""
    path = path or SECURITIES_MASTER
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return {str(r["security_code"]).zfill(6): r.get("exchange", "") for r in csv.DictReader(fh)}


# ---- §9.3.3 比例冷却计数器（买入、涨幅减持、换仓共用；按合格次数计，不按自然日）
DEFAULT_COOLDOWN_STATE = ROOT / "data/processed/daily_cooldown_state.csv"
COOLDOWN_FIELDS = ["security_code", "security_name", "side", "remaining_skips", "remaining_before", "applied_trade_date"]
COOLDOWN_SIDES = ("buy", "sell")


def load_cooldown_state(path: Path, as_of: str) -> tuple[dict[str, dict[str, int]], dict[str, str], bool]:
    """返回 ({"buy": 买入侧计数器, "sell": 卖出侧计数器}, 名称, 可写)。同一信号日重跑从 `remaining_before` 重算（幂等）；
    状态文件的 `applied_trade_date` 晚于 `as_of`（历史重放）时不应用也不回写。无 `side` 列的旧行按买入侧读。"""
    counters: dict[str, dict[str, int]] = {side: {} for side in COOLDOWN_SIDES}
    names: dict[str, str] = {}
    if not path.exists():
        return counters, names, True
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if any((r.get("applied_trade_date") or "") > as_of for r in rows):
        return {side: {} for side in COOLDOWN_SIDES}, {}, False
    for r in rows:
        code = str(r.get("security_code") or "").zfill(6)
        side = (r.get("side") or "buy").strip().lower()
        applied = r.get("applied_trade_date") or ""
        value = to_float(r.get("remaining_before") if applied == as_of else r.get("remaining_skips")) or 0
        if code and side in counters and value > 0:
            counters[side][code] = int(value)
            names[code] = r.get("security_name", "")
    return counters, names, True


def save_cooldown_state(path: Path, before: dict[str, dict[str, int]], after: dict[str, dict[str, int]],
                        names: dict[str, str], as_of: str) -> None:
    rows = []
    for side in COOLDOWN_SIDES:
        b, a = before.get(side, {}), after.get(side, {})
        for code in sorted(set(b) | set(a)):
            if (a.get(code, 0) or 0) <= 0 and (b.get(code, 0) or 0) <= 0:
                continue
            rows.append({"security_code": code, "security_name": names.get(code, ""), "side": side,
                         "remaining_skips": a.get(code, 0), "remaining_before": b.get(code, 0),
                         "applied_trade_date": as_of})
    write_csv(path, rows, COOLDOWN_FIELDS)


def lot_ratio_ready(counters: dict[str, int], code: str, lot_value: float, tranche: float) -> bool:
    """§9.3.3：一手金额是一档的 x 倍时，成交一手后跳过随后 `round(x) − 1` 次合格机会
    （与回测 `lot_ratio_ready` 同式）。计数器 > 0 即本次跳过并减一。"""
    if tranche <= 0 or lot_value <= 0:
        return False
    if counters.get(code, 0) > 0:
        counters[code] -= 1
        return False
    counters[code] = max(1, round(lot_value / tranche)) - 1
    return True


def tranche_sell_shares(tranche: float, price: float, held: float) -> float:
    """减一档的股数：按手向下取整；余仓不足一手时整笔卖出（§9.3.2 第 4 步）。0 = 本档不足一手。"""
    lots = int((tranche / price) // SEC93_LOT)
    if lots <= 0:
        return 0.0
    shares = lots * SEC93_LOT
    return held if held - shares < SEC93_LOT else shares


def hold_pv_of(r: dict[str, object] | None) -> float | None:
    """持仓侧 P/V（v4.92 SPA：§9.3.1 换仓来源读它）；行上无 `hold_pv` 时退回候选侧 `model_pv`。"""
    r = r or {}
    for key in ("hold_pv", "model_pv"):
        if isinstance(r.get(key), float):
            return r[key]
    return None


def holding_trim_signal(close: float | None, ma20: float | None,
                        cost: float | None) -> tuple[str, str]:
    """§9.3.1 涨幅减持行的唯一判定（扫描器与跟踪器同用）。
    收盘 ≥ 持仓均价 × (1 + SEC93_GAIN_SELL) 即命中，不看走势；`ma20` 只为保持调用签名，不参与判定。
    返回 (命中规则, 说明)：规则为 `涨幅减持`／空。"""
    if close is None:
        return "", ""
    gain = (close / cost - 1.0) if (cost is not None and cost > 0) else None
    if gain is None or gain < SEC93_GAIN_SELL:
        return "", ""
    return "涨幅减持", ""


SELL_FIELDS = ["trade_date", "security_code", "security_name", "rule", "condition", "close", "ma20", "ma60",
               "model_pv", "hold_pv", "cost_basis", "gain_pct", "entry_stop_price", "stop_line",
               "current_shares", "sell_shares", "amount", "swap_for", "cooldown_skips", "note"]


def section93_execution_plan(rows: list[dict[str, object]], nav: float, funds: float | None = None,
                             holdings: dict[str, dict[str, object]] | None = None,
                             blocked: set[str] | None = None,
                             tactical_gated: set[str] | None = None,
                             members: set[str] | None = None,
                             counters: dict[str, int] | None = None,
                             holding_rows: list[dict[str, object]] | None = None,
                             sell_counters: dict[str, int] | None = None) -> dict[str, object]:
    """§9.3.2 全部六步：先卖后买。

    卖出侧（第 4 步）逐持仓判：⓪止损复核（T+1 尾盘现价对当日生效线，本表只列候选、不计其卖出款）、
    ②出 `worth_attention` 每日减一档（不加走势条件）、①涨幅 ≥ 125% 且 `收盘 < MA20` 减一档、
    ③换仓（资金不足一档时：先换涨幅达标的弱势持仓，否则换最贵的弱势持仓且 P/V 差 ≥ 换仓差）、
    ④任何减档后余仓不足一手清空。涨幅减持与换仓卖出款当日计入可用资金。
    买入侧（第 3、5 步）：`P/V` 升序、去相关、逐个买一档；高价股一档买不起一手时按 §9.3.3 计数器买一手或跳过。
    `counters` 是买入侧计数器、`sell_counters` 是卖出侧计数器（§9.3.3，两侧互不消费）。
    `holding_rows`：不在输入池内的持仓行情（出名单／无法估值者），只进卖出侧。
    """
    holdings = holdings or {}
    counters = counters if counters is not None else {}
    sell_counters = sell_counters if sell_counters is not None else {}
    blocked = blocked or set()
    tactical_gated = tactical_gated or set()
    tranche = nav * SEC93_TRANCHE_PCT
    held_codes = set(holdings)
    by_code: dict[str, dict[str, object]] = {str(r["security_code"]).zfill(6): r for r in rows}
    for r in holding_rows or []:
        by_code.setdefault(str(r["security_code"]).zfill(6), r)

    def trend_ok(r) -> bool:
        c, m20, m60 = to_float(r.get("close")), to_float(r.get("ma20")), to_float(r.get("ma60"))
        if not (c and m20 and m60) or not m20 > m60:
            return False
        if str(r["security_code"]).zfill(6) in held_codes:
            return True                      # 已持仓：只看均线排列
        return c > m20                       # 新建仓：还要站上 MA20

    # ---------------- 卖出侧
    # §10.2：`--funds` 为负（券商可用保证金为负、已超授信）时照负值起算——卖出款先补足该缺口，余额才进买入；
    # 负预算在买入段落入「不足一手」分支跳过，不会产生负手数。
    cash = nav if funds is None else funds
    funds0 = cash
    sells: list[dict[str, object]] = []
    sell_notes: list[tuple[str, str]] = []     # (名称, 说明)：条件成立但未卖的解释行
    missing_holdings: list[str] = []

    def sell_row(code: str, r: dict[str, object] | None, rule: str, condition: str, shares: float,
                 price: float | None, cooldown: int = 0, swap_for: str = "", note: str = "") -> dict[str, object]:
        h = holdings[code]
        cost = h.get("cost")
        close = price
        gain = (close / cost - 1.0) if (close and cost and cost > 0) else None
        return {
            "trade_date": "", "security_code": code, "security_name": h.get("name", ""),
            "rule": rule, "condition": condition,
            "close": close if close is not None else "",
            "ma20": to_float((r or {}).get("ma20")) or "", "ma60": to_float((r or {}).get("ma60")) or "",
            "model_pv": (r or {}).get("model_pv", "") if isinstance((r or {}).get("model_pv"), float) else "",
            "hold_pv": hold_pv_of(r) if hold_pv_of(r) is not None else "",
            "cost_basis": cost if cost is not None else "", "gain_pct": round(gain, 4) if gain is not None else "",
            "entry_stop_price": h.get("stop") if h.get("stop") is not None else "",
            "stop_line": "", "current_shares": h["shares"], "sell_shares": shares,
            "amount": round(shares * close, 2) if (close and shares) else "",
            "swap_for": swap_for, "cooldown_skips": cooldown, "note": note,
        }

    def reduce_one(code: str, r: dict[str, object], rule: str, condition: str, price: float,
                   swap_for: str = "") -> float:
        """减一档（含 §9.3.3 高价股按手）。返回卖出股数并记入清单；0 = 冷却中跳过或不足一手。"""
        held = float(holdings[code]["shares"])
        shares = tranche_sell_shares(tranche, price, held)
        cooldown = 0
        if not shares and held >= SEC93_LOT:
            if lot_ratio_ready(sell_counters, code, price * SEC93_LOT, tranche):
                shares = SEC93_LOT if held - SEC93_LOT >= SEC93_LOT else held
                cooldown = sell_counters.get(code, 0)
            else:
                sell_notes.append((holdings[code].get("name", code),
                                   f"{rule}命中但一手金额 > 一档，§9.3.3 冷却中跳过（余 {sell_counters.get(code, 0)} 次）"))
                return 0.0
        if not shares:
            return 0.0
        note = "余仓不足一手，整笔清空" if shares >= held else ""
        sells.append(sell_row(code, r, rule, condition, shares, price, cooldown, swap_for, note))
        holdings[code]["shares"] = held - shares
        return shares

    for code, h in holdings.items():
        r = by_code.get(code)
        price = to_float((r or {}).get("close"))
        if r is None or price is None or price <= 0:
            missing_holdings.append(h.get("name", code))
            sells.append(sell_row(code, r, "数据缺失", "无当日行情，未进任何判定", 0, None,
                                  note="停牌或取数失败：按 §9.1 执行日停牌跳过并复核"))
            continue
        ma20, ma60 = to_float(r.get("ma20")), to_float(r.get("ma60"))
        pv = hold_pv_of(r)                                   # 持仓侧 P/V（v4.92 SPA：换仓来源按它判）
        # ⓪ 止损复核：生效线 = min(锚, 当日 MA60)；T+1 尾盘现价跌破 T+1 当日线即整仓清空
        stop = h.get("stop")
        if stop:
            line = min(stop, ma60) if ma60 else stop
            if price < line:
                row = sell_row(code, r, "止损复核", f"T+1 尾盘现价 < min(锚 {stop:g}, T+1 当日 MA60)", h["shares"], price,
                               note="T 日收盘已低于生效线；T+1 复核仍跌破即整仓清空、不走当日其他路径，卖出款不计入本表买入预算")
                row["stop_line"] = round(line, 4)
                sells.append(row)
        # ② 出名单：每日减一档，不加走势条件
        if members is not None and code not in members:
            sold = reduce_one(code, r, "出名单", "已移出 worth_attention，每日减一档直至清空", price)
            cash += sold * price
            continue
        # ① 涨幅减持：涨幅 ≥ 110%，不看走势
        rule, why = holding_trim_signal(price, ma20, h.get("cost"))
        if rule:
            cond = f"收盘 {price:g} ≥ 均价 {h.get('cost'):g}×{1 + SEC93_GAIN_SELL:.2f}（不看走势）"
            sold = reduce_one(code, r, rule, cond, price)
            cash += sold * price
        elif why:
            sell_notes.append((h.get("name", code), why))

    # ---------------- 合格集
    frozen_out = [r for r in rows
                  if str(r["security_code"]).zfill(6) in blocked
                  and isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
                  and trend_ok(r)]
    tactical_out = [r for r in rows
                    if str(r["security_code"]).zfill(6) in tactical_gated
                    and isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
                    and trend_ok(r)
                    and str(r["security_code"]).zfill(6) not in blocked]
    eligible = [
        r for r in rows
        if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE
        and trend_ok(r)
        and str(r["security_code"]).zfill(6) not in blocked
        and str(r["security_code"]).zfill(6) not in tactical_gated
    ]
    eligible.sort(key=lambda r: r["model_pv"])
    n_cheap = sum(1 for r in rows
                  if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC93_BUY_LINE)

    # ---------------- ③ 换仓：想买未持仓候选而可用资金不足一档时，先卖一档弱势持仓（相关性过滤之前，与回测同序）
    swap_targets: set[str] = set()
    reduced_today: set[str] = set()
    swap_stop_reason = ""
    swap_src_meta: dict[str, tuple[float | None, str]] = {}   # 卖出源 → (源持仓侧 P/V 或 None, 触发者)
    if funds is not None:
        for cand in eligible:
            ccode = str(cand["security_code"]).zfill(6)
            if ccode in held_codes:
                continue
            if cash >= tranche:
                break
            gain_src = []
            weak_src = []
            for hcode, h in holdings.items():
                if hcode in reduced_today or float(h["shares"]) <= 0:
                    continue
                hr = by_code.get(hcode)
                hp, hm20 = to_float((hr or {}).get("close")), to_float((hr or {}).get("ma20"))
                if hp is None:
                    continue
                cost = h.get("cost")
                if cost and cost > 0 and hp >= cost * (1.0 + SEC93_GAIN_SELL):
                    gain_src.append((hp / cost - 1.0, hcode))   # 涨幅源不要求弱势（§9.3.1 换仓行）
                    continue
                if hm20 is None or not hp < hm20:
                    continue                                   # 其余只换走势已走坏（收盘 < MA20）的持仓
                hpv = hold_pv_of(hr)                          # 换仓来源按持仓侧 P/V（v4.92 SPA）
                if hpv is not None:
                    weak_src.append((hpv, hcode))
            src_pv = None
            if gain_src:
                gain, worst = max(gain_src)
                cond = f"涨幅 {gain:.0%} ≥ {SEC93_GAIN_SELL:.0%}（不要求弱势），让位给 {cand.get('security_name', ccode)}"
            else:
                if not weak_src:
                    swap_stop_reason = "无弱势持仓可换"
                    break
                worst_pv, worst = max(weak_src)
                if worst_pv - cand["model_pv"] < SEC93_SWAP_MARGIN:
                    swap_stop_reason = (f"最贵弱势持仓 持仓侧 P/V {worst_pv:.4f} 与候选 {cand.get('security_name', ccode)} "
                                        f"P/V {cand['model_pv']:.4f} 差 {worst_pv - cand['model_pv']:.4f} < {SEC93_SWAP_MARGIN:.4f}")
                    break
                src_pv = worst_pv
                cond = (f"持仓侧 P/V {worst_pv:.4f} − 候选 {cand.get('security_name', ccode)} {cand['model_pv']:.4f} "
                        f"≥ {SEC93_SWAP_MARGIN:.4f} 且弱势")
            hr = by_code[worst]
            hp = to_float(hr.get("close")) or 0.0
            sold = reduce_one(worst, hr, "换仓", cond, hp, swap_for=ccode)
            reduced_today.add(worst)
            if sold:
                cash += sold * hp
                swap_targets.add(ccode)
                swap_src_meta[worst] = (src_pv, ccode)

    # ---------------- 相关性（只计算并列报告；SEC93_MAX_CORR = 1.0 时无一被剔除）
    held_rows = [by_code[c] for c in holdings if c in by_code and float(holdings[c]["shares"]) > 0]
    picked: list[dict] = []
    dropped: list[tuple[dict, float, str]] = []
    corr_unknown: list[tuple[dict, str]] = []
    for cand in eligible[:SEC93_SCAN_DEPTH]:
        code = str(cand["security_code"]).zfill(6)
        worst, worst_name = 0.0, ""
        unknown: list[str] = []
        for held in held_rows + picked:
            other = str(held["security_code"]).zfill(6)
            if other == code:
                continue
            value = corr_252(code, other)
            if value is None:
                unknown.append(str(held.get("security_name", "")) or other)
                continue
            if value > worst:
                worst, worst_name = value, str(held.get("security_name", ""))
        if worst_name:
            cand["corr_max"], cand["corr_with"] = worst, worst_name   # 只列报告（§9.3.1 相关性行）
        if worst > SEC93_MAX_CORR:
            dropped.append((cand, worst, worst_name))
            continue
        if unknown:
            corr_unknown.append((cand, "、".join(dict.fromkeys(unknown))))
        picked.append(cand)

    # ---------------- 买入
    plan, capped, cooled = [], [], []
    for cand in picked:
        price = to_float(cand.get("close")) or 0.0
        if price <= 0:
            continue
        code = str(cand["security_code"]).zfill(6)
        lot_amount = price * SEC93_LOT
        budget = min(tranche, cash)
        held_value = float(holdings.get(code, {}).get("shares", 0.0) or 0.0) * price
        room = None
        if SEC93_POSITION_CAP and nav > 0:
            room = nav * SEC93_POSITION_CAP - held_value
            if room <= 0:
                capped.append((cand, held_value / nav))
                continue
            budget = min(budget, room)
        lots = int(budget // lot_amount)
        cooldown = 0
        if lots <= 0:
            if room is not None and room < lot_amount and cash >= lot_amount:
                capped.append((cand, held_value / nav))
                continue
            # 高价股／可用资金不足一手：§9.3.3 计数器决定本次买一手还是跳过
            if lot_ratio_ready(counters, code, lot_amount, tranche) and cash >= lot_amount:
                lots, cooldown = 1, counters.get(code, 0)
            else:
                cooled.append((cand, counters.get(code, 0), cash < lot_amount))
                continue
        amount = lots * lot_amount
        cash -= amount
        plan.append({
            "trade_date": "",
            "security_code": code,
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
    # 换仓行的报告口径（用户 2026-08-31 指令）：依据以**实际接收方**的边际为主、触发者降为附注。
    # 授权卖出的那把尺是「源持仓侧 P/V − 接收方候选侧 P/V ≥ SEC93_SWAP_MARGIN」，此前只量了
    # 触发者，而卖出款按 §9.3.2 第 5 步不定向、按 P/V 升序流向全场，两者常常不是同一只。
    for s in sells:
        if s["rule"] != "换仓" or str(s["security_code"]).zfill(6) not in swap_src_meta:
            continue
        src_pv, tcode = swap_src_meta[str(s["security_code"]).zfill(6)]
        if plan:
            parts = []
            for p in plan:
                nm = p["security_name"] or p["security_code"]
                pv = p["model_pv"]
                if src_pv is None or not isinstance(pv, float):
                    parts.append(str(nm))
                    continue
                m = src_pv - pv
                parts.append(f"{nm} {pv:.4f}（边际 {m:+.4f}{'⚠不足' if m < SEC93_SWAP_MARGIN else ''}）")
            dest_txt = "、".join(parts)
            if sum(1 for x in sells if x["rule"] == "换仓") > 1:
                dest_txt += "（当日换仓卖出款合并投放）"
        else:
            dest_txt = "无——卖出款当日未投出"
        trow = by_code.get(tcode) or {}
        tname = str(trow.get("security_name", "")) or tcode
        tpv = trow.get("model_pv")
        gate = f"｜触发闸门：{tname}"
        if isinstance(tpv, float):
            gate += f" {tpv:.4f}"
            if src_pv is not None:
                gate += f"（差 {src_pv - tpv:.4f} ≥ {SEC93_SWAP_MARGIN:.4f}）"
        head = (f"持仓侧 P/V {src_pv:.4f} 且弱势" if src_pv is not None
                else str(s["condition"]).split("，让位给")[0])
        s["condition"] = f"{head}｜卖出款去向：{dest_txt}{gate}"

    # §9.3.2 第 6 步：同一信号日同一只股票买卖并存时按较小者对冲，只执行净额，双边费税都不付。
    # 只对涨幅减持、换仓两条生效：「出名单」是强制退出、同日买入本就不该发生（§10.1 第 1 条），
    # 抵消会把该矛盾盖住；「止损复核」是提示行、并未在本函数里减仓，故只提示不抵消。
    NETTABLE = ("涨幅减持", "换仓")
    by_plan = {str(p["security_code"]).zfill(6): p for p in plan}
    netted_rows: list[tuple[str, float]] = []
    for srow in sells:
        code = str(srow["security_code"]).zfill(6)
        p_row = by_plan.get(code)
        if not p_row or srow["rule"] not in NETTABLE:
            continue
        n = min(float(srow["sell_shares"]), float(p_row["shares"]))
        if n <= 0:
            continue
        px = to_float(p_row["close"]) or 0.0
        srow["sell_shares"] = float(srow["sell_shares"]) - n
        srow["amount"] = round(float(srow["sell_shares"]) * px, 2) if srow["sell_shares"] else ""
        srow["note"] = (str(srow["note"]) + "；" if srow["note"] else "") + f"同日对冲 {n:.0f} 股"
        p_row["shares"] = float(p_row["shares"]) - n
        p_row["lots"] = int(p_row["shares"] // SEC93_LOT)
        p_row["amount"] = round(float(p_row["shares"]) * px, 2)
        netted_rows.append((code, n))
    sells[:] = [r for r in sells if r["rule"] not in NETTABLE or float(r["sell_shares"]) > 0]
    plan[:] = [r for r in plan if float(r["shares"]) > 0]
    stop_conflict = [str(r["security_name"]) for r in sells
                     if r["rule"] == "止损复核" and str(r["security_code"]).zfill(6) in by_plan]

    # 持仓侧与候选侧 P/V 不同的持仓（报告用：换仓来源按持仓侧判，读者要能看到两侧数）
    hold_pv_diff = [(h.get("name", code), by_code[code]["hold_pv"], by_code[code]["model_pv"])
                    for code, h in holdings.items()
                    if code in by_code and isinstance(by_code[code].get("hold_pv"), float)
                    and isinstance(by_code[code].get("model_pv"), float)
                    and abs(by_code[code]["hold_pv"] - by_code[code]["model_pv"]) > 5e-5]
    return {"plan": plan, "sells": sells, "sell_notes": sell_notes, "missing_holdings": missing_holdings,
            "netted": netted_rows, "stop_conflict": stop_conflict,
            "hold_pv_diff": hold_pv_diff,
            "swap_targets": swap_targets, "swap_stop_reason": swap_stop_reason,
            "dropped": dropped, "corr_unknown": corr_unknown,
            "eligible": eligible, "capped": capped, "cooled": cooled,
            "frozen_out": frozen_out, "tactical_out": tactical_out,
            "n_cheap": n_cheap, "cash": cash, "tranche": tranche,
            "funds0": funds0, "funds_given": funds is not None,
            "n_held": len(holdings),
            "n_addon": sum(1 for r in eligible
                           if str(r["security_code"]).zfill(6) in held_codes
                           and not (to_float(r.get("close")) or 0) > (to_float(r.get("ma20")) or 0))}


def section93_entry_plan(rows: list[dict[str, object]], nav: float, funds: float | None = None,
                         holdings: dict[str, float] | None = None,
                         blocked: set[str] | None = None,
                         tactical_gated: set[str] | None = None) -> dict[str, object]:
    """买入侧兼容入口：只给股数的持仓字典（无成本／止损）→ 走完整执行层，卖出侧只可能出「出名单」
    （无成本即无涨幅减持、无止损）。生产入口是 `section93_execution_plan`。"""
    detail = {c: {"name": "", "shares": s, "cost": None, "stop": None} for c, s in (holdings or {}).items()}
    return section93_execution_plan(rows, nav, funds, detail, blocked, tactical_gated, members=None, counters={})


# `daily_entry_plan.csv` 的固定列。空计划也要写出带表头的空文件——OI-065：买入 0 只时
# 不写文件，旧计划就原样留在盘上冒充当日结论（判例 2026-08-18：文件内容还是 08-14 的四条买入）。
PLAN_FIELDS = ["trade_date", "security_code", "security_name", "quality_tier", "close",
               "model_intrinsic_value", "model_pv", "model_band_source",
               "lots", "shares", "amount", "cooldown_skips"]


def report_section93(result: dict[str, object], nav: float, out_path: Path,
                     as_of: str = "", sell_out: Path | None = None) -> None:
    plan, dropped = result["plan"], result["dropped"]
    sells = result.get("sells") or []
    for p in plan:
        p["trade_date"] = as_of
    for s in sells:
        s["trade_date"] = as_of
    sold_cash = sum(float(s["amount"] or 0) for s in sells if s["rule"] not in ("止损复核", "数据缺失"))
    invested = float(result["funds0"]) + sold_cash - result["cash"]
    print(f"\n§9.3 机械执行（§9.2 四张表）")
    print(f"  1. 一档 {result['tranche'] / 1e4:,.2f} 万（净资产 {nav / 1e4:,.2f} 万 × {SEC93_TRANCHE_PCT:.1%}）")
    print(f"  2. 合格集：`P/V ≤ {SEC93_BUY_LINE}` 的 {result['n_cheap']} 只；"
          f"再过走势条件的 **{len(result['eligible'])} 只**"
          f"（新建仓 `收>MA20>MA60`；**已持仓只须 `MA20>MA60`**，其中 {result['n_addon']} 只"
          f"是靠这条放宽进来的回踩加仓）；"
          f"§7.5 冻结硬排除 {len(result.get('frozen_out') or [])} 只；"
          f"L3 战术闸门排除 {len(result.get('tactical_out') or [])} 只；"
          f"相关性只列报告不过滤（上限 {SEC93_MAX_CORR:g}，剔除 {len(dropped)} 只）")
    for r in result["eligible"]:
        print(f"     {r['security_code']} {str(r.get('security_name', '')):<9}｜P/V {r['model_pv']:.4f}"
              + ("｜换仓目标" if str(r['security_code']).zfill(6) in (result.get('swap_targets') or set()) else "")
              + (f"｜相关 {r['corr_max']:.2f}（{r['corr_with']}）" if r.get("corr_with") else ""))
    for tg in result.get("tactical_out") or []:
        print(f"     [L3 战术闸门排除·§9.3.1] {tg.get('security_name','')} P/V {tg['model_pv']:.2f}"
              f"（分层表 tactical_thesis 为空或判「无」；补判为条件式战术理由后按当日名次重入）")
    for fz in result.get("frozen_out") or []:
        print(f"     [冻结排除·review_pending] {fz.get('security_name','')} P/V {fz['model_pv']:.2f}"
              f"（两闸已开，待 §6.7 重建解冻后按当日名次重入）")
    for cand, value, who in dropped:
        print(f"     [相关性剔除] {cand.get('security_name','')} P/V {cand['model_pv']:.2f}｜与已选 {who} 相关 {value:.2f}")
    for cand, who in result.get("corr_unknown") or []:
        print(f"     [相关性缺数据·OI-093] {cand.get('security_name','')} P/V {cand['model_pv']:.2f}"
              f"｜与 {who} 的重叠K线不足 {CORR_MIN_OVERLAP} 根，按未知放行（与回测同语义），如需人工核对相关性再执行")
    if result["n_held"] == 0:
        print("  ⚠ **没读到任何持仓**（data/processed/a_share_holdings.csv 缺失或为空）"
              "——卖出清单为空、加仓放宽退回旧口径，买入计划不可直接照做")
    else:
        cap_txt = f"单票上限 {SEC93_POSITION_CAP:.0%}（只挡加仓、不触发卖出）" if SEC93_POSITION_CAP else "单票无上限"
        print(f"     持仓 {result['n_held']} 只已载入｜{cap_txt}")
        for name, hpv, cpv in result.get("hold_pv_diff") or []:
            print(f"     [持仓侧带] {name}：持仓侧 P/V {hpv:.4f}（候选侧 {cpv:.4f}）——换仓来源按持仓侧判")
    # 3. 卖出清单
    print(f"  3. 卖出清单：{len([s for s in sells if s['rule'] not in ('数据缺失',)])} 条"
          + ("（**今日无卖出**）" if not sells else ""))
    for s in sells:
        amt = f"{float(s['amount']) / 1e4:.2f} 万" if s["amount"] != "" else "—"
        print(f"     [{s['rule']}] {s['security_code']} {str(s['security_name']):<9}"
              f"｜{s['condition']}｜卖 {s['sell_shares']:g} 股 {amt}"
              + (f"｜触发者 {s['swap_for']}" if s["swap_for"] else "")
              + (f"｜其后跳过 {s['cooldown_skips']} 次" if s["cooldown_skips"] else "")
              + (f"｜{s['note']}" if s["note"] else ""))
    for name, why in result.get("sell_notes") or []:
        print(f"     [未卖·说明] {name}：{why}")
    if result.get("swap_stop_reason"):
        print(f"     [换仓停止] {result['swap_stop_reason']}")
    for code, n in result.get("netted") or []:
        print(f"     [同日对冲] {code} 当日买卖并存，按 {n:.0f} 股抵消，只执行净额，双边费税不付")
    for name in result.get("stop_conflict") or []:
        print(f"     [⚠ 止损冲突] {name} 当日既在止损复核又在买入清单——止损命中即整仓清空，不得同日买回")
    # 4. 买入清单
    if result["funds_given"]:
        funds0 = float(result["funds0"])
        left = float(result["cash"])
        funds_txt = (f"可用资金 {funds0 / 1e4:,.2f} 万（现金＋未用授信）" if funds0 >= 0 else
                     f"可用资金 **{funds0 / 1e4:,.2f} 万（为负：已超授信 {-funds0 / 1e4:,.2f} 万，§10.2 卖出款先补缺口）**")
        left_txt = f"余 {left / 1e4:,.2f} 万" if left >= 0 else f"**仍超授信 {-left / 1e4:,.2f} 万，不可新增买入**"
        print(f"  4. 买入清单：{funds_txt}"
              f"＋ 当日涨幅减持/换仓卖出款 {sold_cash / 1e4:,.2f} 万 → 投入 {invested / 1e4:,.2f} 万"
              f"（占净资产 {invested / nav * 100:.1f}%）｜{left_txt}")
    else:
        print(f"  4. 买入清单：⚠ **未给 `--funds`，按「可用资金＝净资产」估算、不做换仓**"
              f"（OI-062：满仓/带融资账户上此计划资金上不可执行）"
              f"｜投入 {invested / 1e4:,.1f} 万（仓位 {invested / nav * 100:.1f}%）｜余 {result['cash'] / 1e4:,.1f} 万")
    for cand, w in result["capped"]:
        print(f"     [单票上限挡下] {cand.get('security_name','')} P/V {cand['model_pv']:.2f}"
              f"｜现持仓已占净资产 {w:.1%}，已达/不足一手可补至 {SEC93_POSITION_CAP:.0%} 上限，不加仓")
    no_cash_skips = [cand for cand, _r, no_cash in (result.get("cooled") or []) if no_cash]
    for cand, remaining, no_cash in result.get("cooled") or []:
        if not no_cash:
            print(f"     [冷却跳过·§9.3.3] {cand.get('security_name','')} P/V {cand['model_pv']:.2f}"
                  f"｜一手 {to_float(cand.get('close')) * SEC93_LOT / 1e4:.2f} 万 > 一档｜余 {remaining} 次")
    if no_cash_skips:
        print(f"     资金用尽即停：{len(no_cash_skips)} 只合格候选不足一手未买（"
              + "、".join(str(c.get('security_name', '')) for c in no_cash_skips[:6])
              + ("…" if len(no_cash_skips) > 6 else "") + "）")
    for i, p in enumerate(plan, 1):
        band = f"{p['model_intrinsic_value'] * 0.9:.2f}-{p['model_intrinsic_value'] * 1.1:.2f}" \
            if isinstance(p["model_intrinsic_value"], float) else "—"
        print(f"     {i:>3} {p['security_code']} {p['security_name']:<9}"
              f"｜现价 {p['close']:>8.2f}｜带 {band:>17}｜P/V {p['model_pv']:.2f}"
              f"｜{p['shares']:>5} 股 {p['amount'] / 1e4:>5.2f} 万"
              + (f"｜其后跳过 {p['cooldown_skips']} 次" if p["cooldown_skips"] else ""))
    if not plan:
        print("     今日无合格标的，持币")
    # OI-065：**空计划也必须落盘**（只含表头），否则前一日的旧计划会原样留在盘上冒充今日结论。
    write_csv(out_path, plan, PLAN_FIELDS)
    print(f"  买入计划已写 {out_path}（trade_date={as_of or '—'}，{len(plan)} 条"
          + ("；**今日买入为空，已写空文件覆盖旧计划**）" if not plan else "）"))
    if sell_out is not None:
        write_csv(sell_out, sells, SELL_FIELDS)
        print(f"  卖出清单已写 {sell_out}（{len(sells)} 条"
              + ("；**今日卖出为空，已写空文件覆盖旧清单**）" if not sells else "）"))


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
    "fair_price_low",
    "fair_price_high",
    "band_position",
    "margin_of_safety",
    # §9.3 用的模型带三列。**与 fair_price_low/high 并存不混用**：
    # 前者是逐票档案带、只作展示；这三列是批量模型带、供 §9.3 买入判定。
    "model_intrinsic_value",
    "model_band_source",
    "model_pv",
    # v4.92 SPA 持仓侧带三列：换仓来源读 `hold_pv`；持仓侧带缺失时等于候选侧三列。
    "hold_intrinsic_value",
    "hold_band_source",
    "hold_pv",
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
    evidence_date = evidence_iso_for_signal(args.as_of)
    print(f"时点：信号日 {args.as_of} → 证据日 {evidence_date}")
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
        bands = load_model_bands(args.model_bands, evidence_date)
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
        # v4.92 SPA：持仓侧带（换仓来源）。缺文件不静默——退回候选侧并显著告警（§13 第 3 条）。
        if args.hold_bands and args.hold_bands.exists():
            hold_bands = load_model_bands(args.hold_bands, evidence_date)
            attach_model_pv(rows, hold_bands, args.as_of, args.rf, prefix="hold")
            n_hold = sum(1 for r in rows if isinstance(r.get("hold_pv"), float))
            n_diff = sum(1 for r in rows if isinstance(r.get("hold_pv"), float) and isinstance(r.get("model_pv"), float)
                         and abs(r["hold_pv"] - r["model_pv"]) > 5e-5)
            print(f"§9.3 持仓侧带：{len(hold_bands)} 只有带，{n_hold}/{len(rows)} 只算出持仓侧 P/V，其中 {n_diff} 只与候选侧不同"
                  f"（换仓来源按持仓侧判）")
            if rows and priced and not n_hold:
                print("  **告警：hold_pv 整列为空** —— 持仓侧带与池对不上号，换仓来源本次等于按候选侧判")
        else:
            hold_bands = bands
            attach_model_pv(rows, hold_bands, args.as_of, args.rf, prefix="hold")
            print(f"  ⚠ **持仓侧带文件不存在（{args.hold_bands}）**：换仓来源退回候选侧 P/V；重建见 §6.7 第 4 步")
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

    # §9.3 执行清单（`attach_model_pv` 已在落盘前跑过，见上文）：先卖后买，四张表。
    if section93_ready:
        if args.nav > 0:
            holdings = load_holdings_detail(args.holdings)
            pool_codes = {str(r.get("security_code", "")).zfill(6) for r in rows}
            holding_rows: list[dict[str, object]] = []
            outside = [c for c in holdings if c not in pool_codes]
            if outside:
                exchanges = load_exchange_map()
                pseudo = [{"security_code": c, "security_name": holdings[c].get("name", ""),
                           "exchange": exchanges.get(c, "")} for c in outside]
                holding_rows = scan(pseudo, args.as_of, None, args.timeout, args.workers)
                attach_model_pv(holding_rows, bands, args.as_of, args.rf)
                attach_model_pv(holding_rows, hold_bands, args.as_of, args.rf, prefix="hold")
                print(f"  持仓不在输入池 {len(outside)} 只已另取行情（只进卖出侧）："
                      + "、".join(holdings[c].get("name", c) for c in outside))
            members = load_worth_attention_codes(args.triage)
            if members is None:
                print(f"  ⚠ 三类表缺失（{args.triage}）：本次不判「出名单」")
            cd_state, cd_names, cd_writable = load_cooldown_state(args.cooldown_state, args.as_of)
            before = {side: dict(cd_state[side]) for side in COOLDOWN_SIDES}
            if not cd_writable:
                print(f"  ⚠ 冷却计数器 {args.cooldown_state} 的应用日晚于 {args.as_of}（历史重放）：本次不应用、不回写")
            result = section93_execution_plan(rows, args.nav, args.funds, holdings, blocked or set(),
                                              load_tactical_gate_codes(), members, cd_state["buy"], holding_rows,
                                              sell_counters=cd_state["sell"])
            report_section93(result, args.nav, args.plan_out, args.as_of, args.sell_out)
            if cd_writable:
                for c in set().union(*before.values(), *cd_state.values()):
                    cd_names.setdefault(c, holdings.get(c, {}).get("name", "") or next(
                        (str(r.get("security_name", "")) for r in rows if str(r.get("security_code", "")).zfill(6) == c), ""))
                save_cooldown_state(args.cooldown_state, before, cd_state, cd_names, args.as_of)
                active = [(side, c, n) for side in COOLDOWN_SIDES for c, n in cd_state[side].items() if n > 0]
                print(f"  §9.3.3 冷却计数器已写 {args.cooldown_state}（冷却中 {len(active)} 项"
                      + ("：" + "、".join(f"{cd_names.get(c, c)}[{side}] 余 {n}" for side, c, n in active) if active else "") + "）")
        else:
            print("§9.3 未给 --nav，只算 P/V 不出执行清单（一档以净资产为基数）")
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
