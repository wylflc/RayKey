#!/usr/bin/env python3
"""Screen daily A-share volume-price signals from the core valuation pool."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from a_share_quotes import quote_symbol
from build_a_share_core_valuation_pool import TIER_ELIGIBLE_VALUATIONS, effective_valuation_tier
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

MIN_AMOUNT_MA20 = 50_000_000  # §11.8 流动性门槛：20日均成交额低于5000万元不列买入候选。


def limit_up_threshold_pct(code: str, name: str) -> float:
    """§8.7.3 涨停阈值（pct_chg 为百分数）：主板9.5 / 创业板科创板19 / 北交所29 / 主板ST 4.5。"""
    code = code.zfill(6)
    if code.startswith(("30", "68")):
        return 19.0
    if code.startswith(("43", "83", "87", "88", "92")):
        return 29.0
    if "ST" in (name or "").upper():
        return 4.5
    return 9.5


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
    """后备源：腾讯前复权日线（北交所主源，走 newfqkline）。成交量单位为手（仅用于量比，口径内部一致）；
    成交额接口未提供，以收盘价×成交量×100近似，只影响 §11 流动性门槛的估计。"""
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
        for window in (5, 10, 20, 60, 120, 150, 250):
            if index + 1 >= window:
                row[f"ma{window}"] = mean(float(item["close"]) for item in rows[index + 1 - window : index + 1])
        for window in (5, 20, 60):
            if index + 1 >= window:
                row[f"vol_ma{window}"] = mean(float(item["volume"]) for item in rows[index + 1 - window : index + 1])
        if index + 1 >= 20:
            row["amount_ma20"] = mean(float(item["amount"]) for item in rows[index + 1 - 20 : index + 1])
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


# §6.2.1 矩阵末列 × §8.13：各组合所需最低右侧入场阶段（1=首信号 2=初步承接 3=趋势反转确认 4=突破确认）。
# v1.27 三档重构：锚点按新档语义重述——L1×低估=1（原锚点保留）、L2×较低估=3（承继原 L3×较低估）、
# L2×低估=2（原 L2×中性=3 的比亚迪判例因中性已不可买而失效，改以低估档承接其原意）。属语义搬迁非参数放宽，须 3 个月回放验证。
STAGE_REQUIRED = {
    ("L1", "低估"): 1,
    ("L1", "较低估"): 2,
    ("L1", "中性"): 3,
    ("L2", "低估"): 2,
    ("L2", "较低估"): 3,
    ("L3", "低估"): 3,
}
MEGACAP_MIN_YI = 2000.0  # §8.5.6 巨盘温和放量：总市值阈值（亿，2026-07-17 初始校准）。


def to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def volume_conditions(rows: list[dict[str, float | str]], index: int, megacap_yi: float | None = None) -> dict[str, object] | None:
    """§8.5 六个有效放量条件在任意索引上的判定（供当日与 §8.7.8 历史窗复用）；指标不足返回 None。"""
    row = rows[index]
    vol_ma20 = float(row.get("vol_ma20") or 0.0)
    if vol_ma20 <= 0 or index < 4:
        return None
    day_vol_ratio = float(row["volume"]) / vol_ma20
    vol_3d_ratio = mean(float(item["volume"]) for item in rows[index - 2 : index + 1]) / vol_ma20
    vol_5d_ratio = mean(float(item["volume"]) for item in rows[index - 4 : index + 1]) / vol_ma20
    if index >= 59:
        baseline = mean(float(item["volume"]) for item in rows[index - 59 : index - 19])
        vol_5d_ratio_baseline = mean(float(item["volume"]) for item in rows[index - 4 : index + 1]) / baseline
        baseline_days = sum(1 for item in rows[index - 4 : index + 1] if float(item["volume"]) > baseline * 1.2)
    else:
        vol_5d_ratio_baseline, baseline_days = 0.0, 0
    vol_pct = volume_percentile(rows, index) or 0.0
    ret_5d = pct_return(rows, index, 5) or 0.0

    cond_single = day_vol_ratio >= 1.8
    cond_multi = vol_3d_ratio >= 1.5 or vol_5d_ratio >= 1.4
    cond_baseline = vol_5d_ratio_baseline >= 1.6 and baseline_days >= 3
    cond_stacked = (
        float(row.get("vol_ma5", 0.0)) > vol_ma20 > float(row.get("vol_ma60", math.inf))
        and float(row.get("vol_ma5", 0.0)) / float(row.get("vol_ma60", math.inf)) >= 1.5
    )
    cond_percentile = vol_pct >= 80 and ret_5d > 0.03
    # §8.5.6 巨盘温和放量（v1.02）：总市值>=2000亿且量比>=1.3（或3日>=1.25）且当日收涨；属真实量能命中。
    cond_megacap = bool(
        megacap_yi
        and megacap_yi >= MEGACAP_MIN_YI
        and float(row["pct_chg"]) > 0
        and (day_vol_ratio >= 1.3 or vol_3d_ratio >= 1.25)
    )
    effective = cond_single or cond_multi or cond_baseline or cond_stacked or cond_percentile or cond_megacap
    # v31 封顶只针对「仅 §8.5.5 分位」单独命中；§8.5.6 巨盘命中即不属仅分位（v1.02）。
    percentile_only = cond_percentile and not (cond_single or cond_multi or cond_baseline or cond_stacked or cond_megacap)
    return {
        "day_vol_ratio": day_vol_ratio,
        "vol_3d_ratio": vol_3d_ratio,
        "vol_5d_ratio": vol_5d_ratio,
        "vol_5d_ratio_baseline": vol_5d_ratio_baseline,
        "vol_percentile": vol_pct,
        "effective": effective,
        "percentile_only": percentile_only,
        "megacap": cond_megacap,
    }


def bottom_day_condition(rows: list[dict[str, float | str]], index: int, megacap_yi: float | None = None) -> bool:
    """§8.7.8「当日」条件：有效放量 + 收涨>=3% + 收盘位置>=0.6。"""
    conds = volume_conditions(rows, index, megacap_yi)
    return bool(
        conds
        and conds["effective"]
        and float(rows[index]["pct_chg"]) >= 3.0
        and float(rows[index].get("close_location", 0.0)) >= 0.6
    )


def bottom_reversal_state(rows: list[dict[str, float | str]], index: int) -> bool:
    """§8.7.8 前置状态：距250日最高收盘回撤>=25% 且（20日平台 或 V反已收复MA20）。"""
    if index + 1 < 250:
        return False
    closes = [float(row["close"]) for row in rows[: index + 1]]
    max250 = max(closes[-250:])
    if max250 <= 0:
        return False
    platform = (
        closes[-1] <= max250 * 0.75
        and min(closes[-20:]) > min(closes[-60:-20])
        and min(closes[-20:]) > 0
        and max(closes[-20:]) / min(closes[-20:]) - 1 <= 0.15
    )
    ma20 = rows[index].get("ma20")
    v_reversal = min(closes[-60:]) <= max250 * 0.75 and ma20 is not None and closes[-1] > float(ma20)
    return platform or v_reversal


# ---- §8.7.9 / §8.13 v1.06：底部企稳无量口径、V反计段与阶段延续（校准锚点：双汇7/1、比亚迪7/2、茅台7/14-15）----
LOW_POSITION_DD = 0.15  # 低位：距250日最高收盘回撤>=15%，或收盘在MA250下方
V_REVERSAL_DD = 0.25  # V反语境：近10日最低收盘距250日最高回撤>=25%
PLATFORM_AMP = 0.15  # 平台：近20日收盘振幅上限
PLATFORM_UNDERCUT_TOL = 0.97  # 平台容忍近20日最低 >= 60日最低×0.97（允许小幅磨底假破位）
STAGE_VALID_DAYS = 5  # 阶段有效期（交易日）：期内未失效即延续，新触发即刷新
PERSIST_WINDOW_DAYS = 10  # §8.11.1 持续候选回溯窗（交易日），同时是计段函数的回溯起点
PERSIST_STAGE_MET_DAYS = 8  # §8.11.1 窗内段位达标日数门槛：持续可买而非一日达标
PERSIST_TRIGGER_DAYS = 4  # §8.11.1 窗内新触发日数门槛：反复自我确认而非挂在一次旧触发上延续

# §9.6 深度低估重点关注（v2.11 重定门槛，用户裁定）：安全边际越厚，进入关注列表所需的信号越弱。
# 只解决可见性——不改分级、不改 §8.10 优先级、不改 §8.13 所需段位、不改 §6.2.1 买入资格。
# 两层的门槛口径不同，不是同一条规则的两个数：
#   L1 只有空间一个条件（≥30%），**不再区分低估/较低估**。这是安全的，因为 `margin_of_safety`
#      只在现价低于带底时才计算（带内及以上留空），所以这一条天然限定在 低估∪较低估 之内；
#      而 30% 横跨 §6.2.1.6 分开两档的那条 40% 线，再按档切一刀只会把同一区间劈成两半。
#      v2.01 曾写「L1 ≥40%」，那是把「低估」的定义重述了一遍——恒真条件，降到 30% 才真正放宽。
#   L2 仍要求当日档位=低估（现价低于带底 **且** 空间 ≥40%），并另加空间 ≥50%。
#   L3 不适用：弱护城河 × 深跌正是最典型的价值陷阱，战术层不设低门槛关注通道。
DEEP_VALUE_SPACE = {"L1": 0.30, "L2": 0.50}
DEEP_VALUE_REQUIRE_UNDERVALUED = {"L2"}  # 需在空间门槛之外另require当日档位=低估的层

# §8.7.11 突破日的当日涨幅门槛，**单位是百分数**（+1% 写作 1.0，与 `pct_chg` 同口径）。
# 这里必须写成有单位注释的具名常量：v1.37-v2.11 期间这个值以字面量 `0.03` 写在判据里，
# 而正文声称的是「≥3%」——单位差 100 倍，条件退化成「当日收红」且无人察觉（OI-027）。
BREAKOUT_DAY_MIN_PCT = 1.0


def deep_value_cheap(row: dict) -> bool:
    """深度低估提示的条件①「足够便宜」。**这是盘面描述，不是买入闸门**——买入资格只认
    工作流 §9.7.1。判定与跑批摘要共用一份实现，避免门槛写两处后漂移。"""
    tier = str(row.get("quality_tier", "")).strip()[:2]
    floor = DEEP_VALUE_SPACE.get(tier)
    mos = row.get("margin_of_safety")
    if floor is None or not isinstance(mos, float) or mos < floor:
        return False
    if tier in DEEP_VALUE_REQUIRE_UNDERVALUED:
        return row.get("valuation_tier_effective") == "低估"
    return True


def _bull_at(rows: list[dict[str, float | str]], j: int) -> tuple[bool, bool]:
    row = rows[j]
    close = float(row["close"])
    ma5, ma10, ma20, ma60 = (row.get(k) for k in ("ma5", "ma10", "ma20", "ma60"))
    if None in (ma5, ma10, ma20, ma60):
        return False, False
    daily = close > float(ma5) > float(ma10) > float(ma20) > float(ma60)
    quasi = (
        close > float(ma5) > float(ma10) > float(ma20)
        and close > float(ma60)
        and j >= 5
        and float(ma20) >= float(rows[j - 5].get("ma20") or ma20)
    )
    return daily, quasi


def low_position_state(rows: list[dict[str, float | str]], j: int) -> bool:
    if j + 1 < 250:
        return False
    closes = [float(row["close"]) for row in rows[j - 249 : j + 1]]
    ma250 = rows[j].get("ma250")
    return (max(closes) > 0 and closes[-1] <= max(closes) * (1 - LOW_POSITION_DD)) or (
        ma250 is not None and closes[-1] < float(ma250)
    )


def platform_stable_state(rows: list[dict[str, float | str]], j: int) -> bool:
    """§8.7.9 平台企稳前置：低位 + 近20日窄幅 + 近20日最低不显著低于60日最低。"""
    if j + 1 < 60 or not low_position_state(rows, j):
        return False
    closes = [float(row["close"]) for row in rows[j - 59 : j + 1]]
    last20 = closes[-20:]
    return (
        min(last20) > 0
        and max(last20) / min(last20) - 1 <= PLATFORM_AMP
        and min(last20) >= min(closes) * PLATFORM_UNDERCUT_TOL
    )


def v_reversal_context(rows: list[dict[str, float | str]], j: int) -> bool:
    """V反语境：深回撤且近10日内创过60日收盘新低（刚出坑，无需已收复MA20）。"""
    if j + 1 < 250:
        return False
    closes = [float(row["close"]) for row in rows[j - 249 : j + 1]]
    max250 = max(closes)
    last10, last60 = closes[-10:], closes[-60:]
    return max250 > 0 and min(last10) <= max250 * (1 - V_REVERSAL_DD) and min(last10) <= min(last60) * 1.001


def pullback_to_ma_support(rows: list[dict[str, float | str]], index: int,
                          vol_ma20: float) -> str | None:
    """§8.7.10 回踩关键均线企稳（回撤承接型，v1.37）。

    现有 §8.7.1-8.7.9 全是**向上穿越触发**；本组三个信号补的是「先涨后回、在关键位置
    获得支撑再走」这一类。判定链：中期结构未坏 → 回撤幅度落在「回踩」而非「破位」区间
    → 触及关键均线 → 缩量回踩（获利回吐而非抛售）→ 当日企稳收阳。
    """
    row = rows[index]
    close, low = float(row["close"]), float(row["low"])
    ma20 = to_float(row.get("ma20"))
    ma60 = to_float(row.get("ma60"))
    if ma20 is None or ma60 is None or index < 25:
        return None
    # 前置：中期结构未坏——收盘在 MA60 上方且 MA20 未走平走坏
    ma20_prev = to_float(rows[index - 5].get("ma20"))
    if not (close > ma60 and ma20_prev is not None and ma20 >= ma20_prev):
        return None
    # 回撤幅度：从近 20 日最高价回落 4%-18%。低于 4% 不算回踩，高于 18% 是破位不是回踩。
    window = rows[index - 19: index + 1]
    peak = max(float(r["high"]) for r in window)
    peak_idx = max(range(index - 19, index + 1), key=lambda j: float(rows[j]["high"]))
    drawdown = 1 - close / peak if peak else 0.0
    if not 0.04 <= drawdown <= 0.18:
        return None
    # 触线：近 3 日内触及 MA20/MA60/MA120 之一（取被触及的最高级别，越长越重）
    touched = None
    for name, key, value in (("MA120", "ma120", to_float(row.get("ma120"))),
                             ("MA60", "ma60", ma60), ("MA20", "ma20", ma20)):
        if value is None:
            continue
        # 均线必须**上行**：下行均线不构成支撑，只是下跌过程中的一条线
        prior = to_float(rows[index - 5].get(key))
        if prior is None or value < prior:
            continue
        if any(float(rows[j]["low"]) <= value * 1.02 for j in range(max(0, index - 2), index + 1)):
            touched, touched_value = name, value
            break
    if touched is None:
        return None
    # 缩量回踩：回撤段（自高点日起）均量 ≤ 20 日均量 ×1.1，说明是获利回吐不是抛售
    leg = rows[peak_idx: index + 1]
    if vol_ma20 <= 0 or mean([float(r["volume"]) for r in leg]) > vol_ma20 * 1.1:
        return None
    # 企稳：当日收阳、收在被触均线之上、且高于前一日收盘
    if not (close > float(row["open"]) and close >= touched_value * 0.99
            and close > float(rows[index - 1]["close"])):
        return None
    # **承接必须有量**：无量的企稳只是漂移，不是买盘接手。回放实测缺此条时
    # 20 日中位 −1.3%、胜率 45%（基准 +0.2%/51%）。
    if float(row["volume"]) < max(float(rows[index - 1]["volume"]) * 1.2, vol_ma20 * 0.9):
        return None
    return f"8.7.10 回踩{touched}企稳(回撤{drawdown:.0%})"


def breakout_days_in_window(rows: list[dict[str, float | str]], index: int,
                            megacap_yi: float | None,
                            min_pct: float = BREAKOUT_DAY_MIN_PCT) -> list[int]:
    """§8.7.11 的输入：回看 20 日，找出哪几日构成 8.7.1/8.7.2 式的**创新高式突破日**。

    只认创新高式突破：单纯站上均线太宽松，回放实测导致 8.7.11 触发 534 次、20 日中位 −1.6%。

    `min_pct` 是**当日涨幅**门槛，单位为百分数。它取 `max(breakout_days)` 作锚，因此提高门槛
    会剔掉近的突破日、让更早的那个落进 2-15 日窗口——**它是锚点选择器而不是过滤器**，实测在
    0%~3% 之间不产生鉴别力（详见 §8.7.11 校准表）。参数化是为了让 §12 回放能按不同门槛重算。
    """
    days: list[int] = []
    for j in range(max(60, index - 20), index):
        rj = rows[j]
        cj = float(rj["close"])
        cond_j = volume_conditions(rows, j, megacap_yi)
        if cond_j is None or not bool(cond_j["effective"]):
            continue
        if float(rj["close_location"]) < 0.6:
            continue
        broke_high = any(rj.get(f"prev_high_{w}") is not None and cj > float(rj[f"prev_high_{w}"]) * 1.005
                         for w in (60, 120, 250))
        if broke_high and float(rj["pct_chg"]) >= min_pct:
            days.append(j)
    return days


def pullback_after_breakout(rows: list[dict[str, float | str]], index: int,
                            breakout_days: list[int]) -> str | None:
    """§8.7.11 突破后回踩短均线确认（回撤承接型，v1.37）。

    §8.7.6「平台突破后二次确认」只覆盖「再突破」，不覆盖「回踩 5/10 日线后企稳」——
    后者是突破成立最常见的第二买点。要求突破未被否定（不破突破日收盘 7%）、回踩缩量、
    当日在 MA10 上方收阳。
    """
    if not breakout_days or index < 12:
        return None
    b = max(breakout_days)
    if not 2 <= index - b <= 15:            # 突破后 2-15 个交易日内的回踩才算确认
        return None
    row = rows[index]
    close = float(row["close"])
    ma10 = to_float(row.get("ma10"))
    if ma10 is None:
        return None
    breakout_close = float(rows[b]["close"])
    breakout_volume = float(rows[b]["volume"])
    if close < breakout_close * 0.93:        # 跌超 7% 视为突破失败，不是回踩
        return None
    if not any(float(rows[j]["low"]) <= ma10 * 1.02 for j in range(max(0, index - 2), index + 1)):
        return None
    leg = rows[b + 1: index + 1]
    if not leg or mean([float(r["volume"]) for r in leg]) > breakout_volume * 0.7:
        return None                          # 回踩必须缩量；不缩量说明是派发
    ma10_prev = to_float(rows[index - 5].get("ma10"))
    if ma10_prev is None or ma10 < ma10_prev:      # MA10 须上行
        return None
    if not (close > float(row["open"]) and close >= ma10 * 0.99):
        return None
    if float(row["volume"]) < float(rows[index - 1]["volume"]) * 1.2:   # 承接须有量
        return None
    return f"8.7.11 突破后回踩MA10确认(突破后{index - b}日)"


def limit_up_next_day_absorption(rows: list[dict[str, float | str]], index: int,
                                 limit_up_pct: float, prev_was_shrink_limit_up: bool) -> str | None:
    """§8.7.12 缩量涨停次日承接（回撤承接型，v1.37）。

    §8.7.3 只判涨停当日，而涨停的信息量要到**次日**才兑现：低开被买回、或横盘不抛，
    都说明筹码锁定；高开冲高回落则相反。两条承接路径（放量承接 / 缩量横盘）任一成立即可。
    """
    if not prev_was_shrink_limit_up or index < 2:
        return None
    row, prev = rows[index], rows[index - 1]
    close, open_, pct = float(row["close"]), float(row["open"]), float(row["pct_chg"])
    prev_close, prev_open = float(prev["close"]), float(prev["open"])
    prev_volume = float(prev["volume"])
    volume = float(row["volume"])
    if close < prev_open:                    # 吞没涨停实体 = 承接失败
        return None
    if volume >= prev_volume * 1.5 and close >= prev_close * 0.97 and open_ <= prev_close:
        return f"8.7.12 缩量涨停次日放量承接(量比{volume / prev_volume:.1f})"
    if abs(pct) <= 0.03 and volume <= prev_volume * 1.2:
        return f"8.7.12 缩量涨停次日缩量横盘({pct:+.1%})"
    return None


def stage_day_trigger(rows: list[dict[str, float | str]], j: int, megacap_yi: float | None) -> tuple[int, list[str]]:
    """当日新达段位（0-4）与触发标签（§8.13 v1.06）。8.7.9 各形态不要求 §8.5 有效放量。"""
    row = rows[j]
    close = float(row["close"])
    pct = float(row["pct_chg"])
    loc = float(row.get("close_location") or 0.0)
    conds = volume_conditions(rows, j, megacap_yi)
    dvr = float(conds["day_vol_ratio"]) if conds else 0.0
    eff_vol = bool(conds and conds["effective"])
    pct_only = bool(conds and conds["percentile_only"])
    daily, quasi = _bull_at(rows, j)
    ma5, ma20, ma60 = row.get("ma5"), row.get("ma20"), row.get("ma60")
    stage, tags = 0, []
    plat = platform_stable_state(rows, j)
    vctx = v_reversal_context(rows, j)
    # 一段：平台企稳大阳（无量口径）/ 平台温和转强 / V反启动阳线 / 8.7.8 底部放量反转
    if plat and pct >= 2.5 and loc >= 0.6 and ma5 is not None and close > float(ma5):
        stage = max(stage, 1)
        tags.append("8.7.9a 平台企稳大阳")
    if plat and ma5 is not None and row.get("ma10") is not None and float(ma5) > float(row["ma10"]):
        up3 = j >= 2 and all(
            float(rows[j - k]["close"]) > float(rows[j - k].get("ma5") or 9e18) for k in range(3)
        )
        if up3 and (pct_return(rows, j, 5) or 0.0) >= 0.015:
            stage = max(stage, 1)
            tags.append("8.7.9b 平台温和转强")
    if vctx and pct >= 3.0 and dvr >= 1.3:
        stage = max(stage, 1)
        tags.append("8.7.9c V反启动阳线")
    if bottom_reversal_state(rows, j) and bottom_day_condition(rows, j, megacap_yi):
        hits = sum(1 for k in range(max(60, j - 9), j + 1) if bottom_day_condition(rows, k, megacap_yi))
        stage = max(stage, 2 if hits >= 2 else 1)
        tags.append("8.7.8 底部连续放量" if hits >= 2 else "8.7.8 底部/平台放量反转")
    # 二段：平台上沿新高（量能不限）
    if plat and j >= 19 and close >= max(float(x["close"]) for x in rows[j - 19 : j + 1]):
        stage = max(stage, 2)
        tags.append("8.7.9d 平台上沿新高")
    # 三段：连续3日放量上涨，或 多头/准多头+当日有效放量上涨
    three_up = (
        j >= 3
        and all(float(rows[j - k]["pct_chg"]) > 0 for k in range(3))
        and bool(conds)
        and float(conds["vol_3d_ratio"]) >= 1.5
    )
    if three_up or ((daily or quasi) and eff_vol and pct > 0):
        stage = max(stage, 3)
    # 四段：突破确认口径（多头+有效放量+收位+站上MA20/MA60；仅分位量不计）
    if (
        (daily or quasi)
        and eff_vol
        and not pct_only
        and loc >= 0.6
        and ma20 is not None
        and ma60 is not None
        and close > float(ma20)
        and close > float(ma60)
    ):
        stage = 4
    return stage, tags


def compute_entry_stage(
    rows: list[dict[str, float | str]], index: int, megacap_yi: float | None
) -> tuple[int, int, list[str], list[int], int]:
    """§8.13 v1.06 有效段位（延续口径）：近 STAGE_VALID_DAYS 个交易日内达到的最高段位持续有效；
    承接升段（触发后收盘未破触发日最低价即升二段——放量大涨后的缩量整理是延续不是转弱）；
    有效期内收复MA20且高于触发日收盘 → 三段里程碑；失效条件：收盘跌破触发日最低价，或 放量下跌
    （量比>=1.5且跌>=3%），或超过有效期无新触发。

    返回 (有效段位, 当日新达段位, 当日触发标签, 回溯窗内逐日有效段位, 回溯窗内新触发日数)。
    后两项服务 §8.11.1 持续候选提醒（v1.20）：逐日有效段位供调用方对照所需段位数达标日数，
    新触发日数区分"反复自我确认"与"挂在一次旧触发上延续"。"""
    start = max(60, index - PERSIST_WINDOW_DAYS + 1)
    eff, trig_idx, trig_low, trig_close = 0, None, None, None
    today_stage, today_tags = 0, []
    stage_by_day: list[int] = []
    trigger_days = 0
    for j in range(start, index + 1):
        row = rows[j]
        close = float(row["close"])
        pct = float(row["pct_chg"])
        conds = volume_conditions(rows, j, megacap_yi)
        heavy_down = bool(conds) and float(conds["day_vol_ratio"]) >= 1.5 and pct <= -3.0
        if eff > 0 and (
            (trig_low is not None and close < trig_low)
            or heavy_down
            or (trig_idx is not None and j - trig_idx > STAGE_VALID_DAYS)
        ):
            eff, trig_idx, trig_low, trig_close = 0, None, None, None
        stage, tags = stage_day_trigger(rows, j, megacap_yi)
        if j == index:
            today_stage, today_tags = stage, tags
        if stage > 0:
            if eff == 0:
                trig_low, trig_close = float(row["low"]), close
            trig_idx = j  # 新触发刷新有效期；承接锚（触发日低/收）保持首次触发口径
            eff = max(eff, stage)
            trigger_days += 1
        elif eff == 1 and trig_low is not None and close >= trig_low:
            eff = 2  # 承接升二段
        ma20 = row.get("ma20")
        if eff >= 1 and ma20 is not None and close > float(ma20) and trig_close is not None and close > trig_close:
            eff = max(eff, 3)  # 趋势里程碑：收复MA20且较触发日有浮盈
        stage_by_day.append(eff)
    return eff, today_stage, today_tags, stage_by_day, trigger_days


def classify_signal(
    rows: list[dict[str, float | str]],
    limit_up_pct: float = 9.5,
    cap_bn: float | None = None,
    valuation_price: float | None = None,
    at_index: int | None = None,
) -> dict[str, object]:
    """at_index 缺省为最后一根K线；§8.6 缺口回溯用它在历史任一日重算信号。"""
    add_indicators(rows)
    index = len(rows) - 1 if at_index is None else at_index
    row = rows[index]
    if index < 60 or "ma20" not in row or "ma60" not in row or "vol_ma20" not in row:
        return {"signal_state": "insufficient_price_history", "signals": []}

    close = float(row["close"])
    ma20 = float(row["ma20"])
    ma60 = float(row["ma60"])
    vol_ma20 = float(row["vol_ma20"])
    # §8.5.6 输入：估值时点总市值（十亿）按现价/估值价折算为当前市值（亿）。
    megacap_yi = cap_bn * 10.0 * close / valuation_price if cap_bn and valuation_price else None
    conds = volume_conditions(rows, index, megacap_yi)
    if conds is None:
        return {"signal_state": "insufficient_price_history", "signals": []}
    day_vol_ratio = float(conds["day_vol_ratio"])
    vol_3d_ratio = float(conds["vol_3d_ratio"])
    vol_5d_ratio = float(conds["vol_5d_ratio"])
    vol_5d_ratio_baseline = float(conds["vol_5d_ratio_baseline"])
    vol_percentile = float(conds["vol_percentile"])
    ret_5d = pct_return(rows, index, 5) or 0.0
    ret_20d = pct_return(rows, index, 20) or 0.0
    ret_60d = pct_return(rows, index, 60) or 0.0
    effective_volume = bool(conds["effective"])
    # v31：有效放量仅由 §8.5 第 5 条（高分位放量）单独认定时，信号分级封顶「中」；§8.5.6 巨盘命中不属仅分位（v1.02）。
    percentile_only_volume = bool(conds["percentile_only"])

    daily_bull = close > float(row.get("ma5", math.inf)) > float(row.get("ma10", math.inf)) > ma20 > ma60
    strong_daily_bull = daily_bull and ma60 > float(row.get("ma120", math.inf)) > float(row.get("ma250", math.inf))
    quasi_bull = (
        close > float(row.get("ma5", math.inf)) > float(row.get("ma10", math.inf)) > ma20
        and close > ma60
        and ma20 >= float(rows[index - 5].get("ma20", ma20))
    )
    # §8.6 长期趋势确认（原月线确认，日线化并精简）：close 站上 MA120/MA250 之一。
    long_term_confirm = any(f"ma{w}" in row and close > float(row[f"ma{w}"]) for w in (120, 250))
    close_location = float(row["close_location"])
    break_periods: list[str] = []
    for window in (60, 120, 250, 500, 750):
        previous_high = row.get(f"prev_high_{window}")
        if previous_high is not None and close > float(previous_high) * 1.005:
            break_periods.append(str(window))

    breakout_days = breakout_days_in_window(rows, index, megacap_yi)

    signals: list[str] = []
    wait_reasons: list[str] = []
    limit_up_tag = ""
    if break_periods and effective_volume and close_location >= 0.6:
        signals.append(f"8.7.1 放量突破前高({','.join(break_periods)}日)")
    elif break_periods and effective_volume:
        wait_reasons.append("前高突破但收盘位置不足")

    if close > ma20 and close > ma60 and effective_volume and close_location >= 0.6 and (daily_bull or quasi_bull):
        signals.append("8.7.2 放量突破关键均线/趋势启动")
    elif close > ma20 and close > ma60 and effective_volume and (daily_bull or quasi_bull):
        wait_reasons.append("均线突破但收盘位置不足")

    # 8.7.3 缩量涨停：涨停 +（当日量<=20日均量*1.2，或前日已放量且当日量<=前日量*0.85）。
    prev_vol = float(rows[index - 1]["volume"])
    prev_vol_ma20 = float(rows[index - 1].get("vol_ma20", 0.0) or 0.0)
    shrink_volume = float(row["volume"]) <= vol_ma20 * 1.2 or (
        prev_vol_ma20 > 0 and prev_vol >= prev_vol_ma20 * 1.5 and float(row["volume"]) <= prev_vol * 0.85
    )
    # §8.7.3 v1.38（结 OI-012）：降为**提醒信号**，不作买入触发。
    # 估值合格样本（70 家 / 约 2 年）重测：仅 25 次触发，涨停日买入 20 日中位 −6.0%/胜率 28%，
    # 次日买入 −9.2%/16%，用户提议的「次日涨幅 ≤3% 才买」仅 5 个样本、−9.6%/20%——三种口径
    # 全负。形态本身有识别价值（5 日中位曾达 +3.7%），但持有到 20 日为负期望。
    if float(row["pct_chg"]) >= limit_up_pct and shrink_volume:
        limit_up_tag = "8.7.3 缩量涨停[提醒·历史20日期望为负(-6%/胜率28%)]"

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

    # §8.7.10-8.7.12 回撤承接型（v1.37）：现有信号全是向上穿越触发，本组补「先涨后回、
    # 在关键位置获得支撑再走」这一类——用户点名的三种形态，缺一不可脚本化。
    observation_tags: list[str] = []
    if limit_up_tag:
        observation_tags.append(limit_up_tag)
    # 8.7.11 仍作正式信号，但其「通过 §12 回放」的原始依据（77 次 / +1.4% / 51%）**已不可复现**：
    # v2.12 重跑（259 只 × 2022-06→2026-08）得 1034 次 / −0.85% / 47.3%，逐年跑输同窗基准。
    # 是否按 §12.5 降为观察标记待用户裁定（OI-028）——在裁定前不擅自改变它的身份。
    pullback_bo = pullback_after_breakout(rows, index, breakout_days)
    if pullback_bo:
        signals.append(pullback_bo)
    # 8.7.10 **未通过回放**：加严（均线须上行 + 企稳日须有量）后反而更差——由 330 次/−1.3%/45%
    # 变为 78 次/−3.7%/40%，显著劣于基准 +0.3%/51%。按 §12.5 不得作买入触发，降为观察标记。
    pullback_ma = pullback_to_ma_support(rows, index, vol_ma20)
    if pullback_ma:
        observation_tags.append(pullback_ma + "[观察·未过回放]")
    prev_row = rows[index - 1]
    prev_vol_ma20_v = to_float(prev_row.get("vol_ma20")) or 0.0
    prev_prev_vol = float(rows[index - 2]["volume"]) if index >= 2 else 0.0
    prev_shrink = (float(prev_row["volume"]) <= prev_vol_ma20_v * 1.2) or (
        prev_prev_vol > 0 and float(prev_row["volume"]) <= prev_prev_vol * 0.85)
    prev_limit_up = float(prev_row["pct_chg"]) >= limit_up_pct and prev_shrink
    # 8.7.12 回放样本仅 4 次触发，不足以判定（4 次全负），按 §12.5 先作观察标记、不作买入触发。
    absorption = limit_up_next_day_absorption(rows, index, limit_up_pct, prev_limit_up)
    if absorption:
        observation_tags.append(absorption + "[观察·样本不足]")

    # §8.7.8/§8.7.9 底部反转与企稳形态 + §8.13 v1.06 阶段延续：统一由计段函数判定。
    entry_stage, entry_stage_today, stage_tags, stage_by_day, stage_trigger_days = compute_entry_stage(
        rows, index, megacap_yi
    )
    for tag in stage_tags:
        if tag not in signals:
            signals.append(tag)

    overextended = close / ma20 - 1 > 0.25 or ret_5d > 0.30 or ret_20d > 0.60
    if overextended:
        signal_state = "wait_pullback"
        action_bias = "等回踩"
    elif signals:
        signal_state = "buy_candidate"
        action_bias = "信号成立"
    elif entry_stage >= 1:
        # §8.13.5 阶段延续（v1.06）：触发后的缩量整理日属于信号延续而非转弱，延续窗口内视同候选可按有效段位执行。
        signals.append(f"阶段延续({entry_stage}段)")
        signal_state = "buy_candidate"
        action_bias = "阶段延续窗口内"
    elif wait_reasons:
        signal_state = "wait_confirmation"
        action_bias = "等确认"
    elif close < ma60:
        signal_state = "wait_repair"
        action_bias = "仅观察"
    else:
        signal_state = "wait_breakout"
        action_bias = "仅观察"

    # §11.8 流动性过滤：20日均成交额低于门槛的不列买入候选，仅提示。
    amount_ma20 = float(row.get("amount_ma20", 0.0) or 0.0)
    if signal_state == "buy_candidate" and amount_ma20 < MIN_AMOUNT_MA20:
        signal_state = "liquidity_filtered"
        action_bias = "仅观察（流动性不足）"

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
        if (daily_bull or quasi_bull) and breakout_confirm and not percentile_only_volume:
            signal_grade, action_bias = "强", "信号成立"
        elif daily_bull or quasi_bull:
            signal_grade, action_bias = "中", "信号成立待确认"
        else:
            signal_grade, action_bias = "弱", "等确认"
    else:
        signal_grade = ""

    # §8.13 阶段已由 compute_entry_stage 统一判定（延续口径）；突破确认形态当日再补一次四段判定。
    if signals:
        breakout_confirm_shape = any(sig.startswith(("8.7.1", "8.7.2")) for sig in signals)
        if (daily_bull or quasi_bull) and breakout_confirm_shape and not percentile_only_volume:
            entry_stage = max(entry_stage, 4)

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
        "ma150": row.get("ma150", ""),
        "ma250": row.get("ma250", ""),
        "amount_ma20": row.get("amount_ma20", ""),
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
        "long_term_confirm": long_term_confirm,
        "break_periods": ",".join(break_periods),
        "signals": "; ".join(signals),
        "observation_tags": "; ".join(observation_tags),
        "wait_reasons": "; ".join(wait_reasons),
        "overextended": overextended,
        "signal_state": signal_state,
        "priority": "",
        "action_bias": action_bias,
        "signal_grade": signal_grade,
        "trend_strength": trend_strength,
        "entry_stage": entry_stage,
        "entry_stage_today": entry_stage_today,
        "stage_by_day": stage_by_day,  # §8.11.1 内部中间量，不出 CSV
        "stage_trigger_days": stage_trigger_days,
        "megacap_volume": bool(conds["megacap"]),
        "market_cap_now_yi": megacap_yi or "",
        # §9.6：止跌企稳的最弱可接受证据——§8.7.9 的两个前置状态（平台企稳 / V 反语境）本身，
        # 即使 a-d 四个形态一个都没触发。它们是「跌势已经停住」而非「已经开始涨」，
        # 正是深度低估票需要的那一档信号。
        "stabilizing": bool(platform_stable_state(rows, index) or v_reversal_context(rows, index)),
    }


def gap_review(rows: list[dict[str, float | str]], as_of: str, since: str,
               limit_up_pct: float, cap_bn: float | None, valuation_price: float | None) -> dict[str, object]:
    """§8.6 缺口回溯：把 since→as_of 之间**未被扫描的交易日**逐日重算一遍。

    现行 §9.1 是单日快照——隔一周再扫，期间出现过的放量、反转、信号触发全部不可见，
    只能看到"今天什么样"。缺口回溯逐日重跑 `classify_signal`，回答三件事：
    期间是否触发过任一 §8.7 信号（哪天、什么信号）、最大单日放量倍数、区间涨跌幅。
    """
    idx = {str(r["date"]): j for j, r in enumerate(rows)}
    gap_days = [d for d in idx if since < d <= as_of]
    if len(gap_days) <= 1:
        return {}
    fired: list[str] = []
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
        res = classify_signal(rows, limit_up_pct, cap_bn, valuation_price, at_index=j)
        sig = res.get("signals") or ""
        if sig and d != as_of:                    # 当日信号已由主扫描输出，此处只报"期间曾触发"
            fired.append(f"{d}:{sig}")
    first, last = sorted(gap_days)[0], sorted(gap_days)[-1]
    ret = float(rows[idx[last]]["close"]) / float(rows[idx[first]]["open"]) - 1
    return {
        "gap_trading_days": len(gap_days),
        "gap_return": round(ret, 4),
        "gap_max_vol_ratio": round(max_ratio, 2),
        "gap_max_vol_day": max_ratio_day,
        "gap_signals_fired": "; ".join(fired[-6:]),
        "gap_signal_days": len(fired),
    }


def fetch_market_state(as_of: str, timeout: float) -> str:
    """§8.12：沪深300 收盘与 MA250 判定市场状态（强势/弱势/震荡）。"""
    try:
        _, rows = fetch_daily_rows("000300", "SSE", as_of, timeout)
        closes = [float(row["close"]) for row in rows]
        if len(closes) < 271:
            return "震荡"
        ma250_now = mean(closes[-250:])
        ma250_prev = mean(closes[-270:-20])
        close = closes[-1]
        if close > ma250_now and ma250_now > ma250_prev:
            return "强势"
        if close < ma250_now and ma250_now < ma250_prev:
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
    # v1.05：优先级按当日价格自动定档（§6.2.1.6），不用审定档。
    valuation_tier = str(row.get("valuation_tier_effective") or row.get("valuation_tier", ""))
    break_periods = set(str(row.get("break_periods", "")).split(","))
    if (
        quality_tier == "L1"
        and valuation_tier in {"低估", "较低估", "中性"}
        and break_periods.intersection({"120", "250", "500", "750"})
        and row.get("daily_bull") is True
        and row.get("long_term_confirm") is True
    ):
        return "S"
    # v1.27：B 档（L1×较高估）随三态矩阵删除——L1 较高估改为仅可持有；D 档随 L4 退役删除。
    if quality_tier in {"L1", "L2"} and (quality_tier, valuation_tier) in STAGE_REQUIRED:
        return "A"
    return "C"


def scan_one(pool_row: dict[str, str], as_of: str, timeout: float, since: str = "") -> dict[str, object]:
    code = pool_row["security_code"].zfill(6)
    cap_bn = to_float(pool_row.get("total_market_cap_bn"))
    val_price = to_float(pool_row.get("valuation_price"))
    try:
        kline_url, price_rows = fetch_daily_rows(code, pool_row.get("exchange", ""), as_of, timeout)
        if not price_rows:
            raise RuntimeError("empty kline response")
        limit_up = limit_up_threshold_pct(code, pool_row.get("security_name", ""))
        gap = gap_review(list(price_rows), as_of, since, limit_up, cap_bn, val_price) if since else {}
        signal = classify_signal(price_rows, limit_up, cap_bn, val_price)
        signal.update(gap)
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

    # §6.2.1.6 价格自动定档 + 带内位置（v1.05）：档位由现价 vs 合理价区间每日自动重定，无人工复核；
    # 无法估值不自动定档。买入资格 = 质量 × 当日档位 过 §6.2.1 矩阵。
    close = to_float(signal.get("close"))
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
    signal["band_position"] = band_position
    signal["valuation_tier_effective"] = effective_tier
    signal["valuation_tier_changed"] = effective_tier != stored_tier
    # §9.6 安全边际：合理价区间中值 ÷ 现价 − 1，与 §6.2.1.6 判「低估」所用的「空间」同一个量。
    # 只在现价低于带底时有意义（带内及以上不是安全边际问题），其余留空。
    signal["margin_of_safety"] = (
        round((fair_low + fair_high) / 2 / close - 1, 4)
        if close and fair_low and fair_high and close < fair_low else ""
    )
    eligible = effective_tier in TIER_ELIGIBLE_VALUATIONS.get(pool_row.get("quality_tier", ""), set())
    signal["stage_required"] = (
        STAGE_REQUIRED.get((pool_row.get("quality_tier", ""), effective_tier), "") if eligible else ""
    )

    # §8.9：当日档位未过 §6.2.1 矩阵的组合（含高估/无法估值）出现信号 → 可见不可买。
    if not eligible and signal.get("signal_state") == "buy_candidate":
        signal["signal_state"] = "signal_watch_only"
        signal["action_bias"] = f"当日价格定档 {effective_tier}：未过 §6.2.1 矩阵，仅观察（24小时异动响应+§7.4复核）"
    signal["priority"] = assign_priority(signal)
    signal["data_source"] = kline_url
    signal["screened_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {key: rounded(value) for key, value in signal.items()}


def detect_last_scan(log_path: Path, as_of: str) -> str:
    """§8.6：自动检出上一次扫描日——缺口回溯不能依赖人记得传 --since。"""
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
        help='§8.6 缺口回溯起点。"auto"（缺省）从决策日志检出上次扫描日；'
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
    # ---- §9.7 机械执行层（并入自 experimental，结 OI-051）。三个都给才出买入计划。
    parser.add_argument("--model-bands", type=Path, default=DEFAULT_MODEL_BANDS,
                        help="§6.5.7.1 批量模型带表；§9.7 的 P/V 用它，不用池里的逐票档案带")
    parser.add_argument("--nav", type=float, default=0.0,
                        help="当日净资产，用于定一档 = NAV × §9.7.1 的比例。不给则只算 P/V、不出买入计划")
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


# ------------------------------------------------------------------ §9.7 机械执行层
# 本段并入自 `scripts/experimental/daily_scan_adopted.py`（结 OI-051，2026-08-14）。
# 此前 §9.7 的排序/去相关/定档只存在于 experimental 那份实现里，与本脚本口径重叠、代码独立
# ——「文档说的」与「实际跑的」分叉两次的同一形态。合并后 §8 取数与 §9.7 决策在同一次跑批内完成。
#
# **口径一律来自 `docs/000_Ashare_workflow.md` §9.7，此处不另立标准。** 三处细节：
#   * 走势闸门 `收 > MA20 > MA60` 用**前复权**序列（收盘与均线同尺度，除息不产生假信号）；
#   * `P/V` = **未复权现价 ÷ 当日带**。本脚本的 `close` 取自 `fqt=1` 前复权序列，
#     而前复权序列**锚在最新一根**，故 `--as-of` 为最近交易日时末根收盘即未复权现价，两者同尺度；
#     **回溯历史日期时该等式不成立**，故本层只在 `--as-of` 为最新交易日时给出买入计划。
#   * 银行走工作流 §6.5.1 的股利折现口径。
SEC97_BUY_LINE = 0.9493        # §9.7.1 买入线
SEC97_MAX_CORR = 0.70          # §9.7.1，252 日日收益率皮尔逊相关上限
SEC97_SCAN_DEPTH = 40          # §9.7.2 第 3 步：相关性过滤时最多下扫多少名
SEC97_TRANCHE_PCT = 0.05       # §9.7.1 单次买入比例
SEC97_LOT = 100                # A 股一手
SEC97_POSITION_CAP = None      # §9.7.1：v4.04 起**无单票上限**——用户 2026-08-17 裁定退役仓位控制，
                               # 风险改由回撤与年化承担（§12.75）。None = 不设限，判定处直接跳过。
SEC97_SELL_LINE = 2.5548       # §9.7.1「减持线」，v4.04 对齐解：P/V ≥ 线且收盘 < MA20 → 减一档。
# ↑ 本脚本只做买入侧（§9.7.2 第 4 步卖出是人工），该常量是减持线数值的**脚本侧唯一落点**，
#   供卖出侧人工核对引用——不是静默失效，是成文的分工（见工作流 §9.7.2 末段）。
# §9.7.1「走势条件·加仓」，v3.02：已有持仓只须 `MA20 > MA60`，不要求 `收盘 > MA20`。
# 新建仓仍须 `收盘 > MA20 > MA60`。两者的差别只对**在手持仓**生效，故本脚本必须读持仓。
SEC97_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
BANK_RISK_PREMIUM = 0.02       # §12.31 股利折现的风险溢价


def is_bank(name: str) -> bool:
    return "银行" in name or name.endswith("行") or "农商" in name


def load_model_bands(path: Path, as_of: str) -> dict[str, dict]:
    """§6.5.7.1 批量模型带，逐票取 `available_at ≤ as_of` 的最新一条。

    **不能按报告期排序取最新**——未到披露日的带在当日不可用，那是后视。
    """
    latest: dict[str, tuple[str, dict]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            status = row.get("status")
            if status not in (None, "", "ok"):
                continue
            avail = row.get("band_available_at") or row.get("available_at") or ""
            code = (row.get("security_code") or "").zfill(6)
            if len(avail) == 10 and avail <= as_of and code:
                if code not in latest or avail >= latest[code][0]:
                    latest[code] = (avail, row)
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
    """给每行挂上 §9.7 用的 `model_intrinsic_value` / `model_pv` / `model_band_source`。

    **与 §8 的 `fair_price_low/high`（逐票档案带）并存、互不覆盖**：档案带继续供
    §6.2.1.6 自动定档用，模型带只供 §9.7 用。两者在 28 只上偏离 >50%，故不可混用
    （见 `data/processed/000_a_share_core_valuation_pool.md` 的 ⚠ 标注）。
    """
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
    if not SEC97_HOLDINGS.exists():
        return out
    with SEC97_HOLDINGS.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            shares = to_float(r.get("current_shares"))
            if shares and shares > 0:
                out[str(r["security_code"]).zfill(6)] = shares
    return out


def section97_entry_plan(rows: list[dict[str, object]], nav: float, funds: float | None = None,
                         holdings: dict[str, float] | None = None,
                         blocked: set[str] | None = None) -> dict[str, object]:
    """§9.7.2 第 3、5 步：按 `P/V` 升序、去相关、逐个买一档。

    §9.7.3 比例冷却：一手金额 > 一档时买一手，其后跳过 `round(x)−1` 次合格机会
    （本函数是单日快照，故只记 `cooldown_skips` 供次日跑批读，不在此处消费）。

    **两条与持仓有关的规则（v3.01/v3.02，OI-058／OI-059）**：
    - **走势条件分新旧**：新建仓须 `收盘 > MA20 > MA60`；**已有持仓的加仓只须 `MA20 > MA60`**。
    - **单票上限**：买入后该票市值 ÷ N 超过 `SEC97_POSITION_CAP` 即跳过、顺位补下一名；
      **只挡加仓，已有持仓因上涨越限不回削**。
    `holdings` 为空时两条都退化为原口径，故调用方须把「读到几只持仓」打出来。
    """
    holdings = holdings or {}
    tranche = nav * SEC97_TRANCHE_PCT

    def trend_ok(r) -> bool:
        c, m20, m60 = to_float(r.get("close")), to_float(r.get("ma20")), to_float(r.get("ma60"))
        if not (c and m20 and m60) or not m20 > m60:
            return False
        if str(r["security_code"]).zfill(6) in holdings:
            return True                      # 已持仓：只看均线排列
        return c > m20                       # 新建仓：还要站上 MA20

    # §9.7.2 第 1 步：排除 review_pending（§7.5 冻结）。此前冻结只改 `signal_state` 展示字段、
    # 本函数不读它——冻结股照样进下扫序列（判例 2026-08-19：天山铝业冻结中仍参与排序，
    # 仅因相关性 0.72 被碰巧剔除）。「读起来在保护你、实际不保护任何东西」型，故在合格集处硬排除。
    blocked = blocked or set()
    frozen_out = [r for r in rows
                  if str(r["security_code"]).zfill(6) in blocked
                  and isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC97_BUY_LINE
                  and trend_ok(r)]
    eligible = [
        r for r in rows
        if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC97_BUY_LINE
        and trend_ok(r)
        and str(r["security_code"]).zfill(6) not in blocked
    ]
    eligible.sort(key=lambda r: r["model_pv"])
    n_cheap = sum(1 for r in rows
                  if isinstance(r.get("model_pv"), float) and r["model_pv"] <= SEC97_BUY_LINE)

    # **相关性基准必须含在手持仓**：§9.7.1 写的是「与**在手**/已选标的 ≤ 上限」，
    # 而此前这里只用 `picked`（当日已选候选）作基准，**持仓被完全忽略**——回测侧 `--max-corr`
    # 一直是对「在手 + 已选」判的，两侧口径因此分叉。判例：2026-08-17 持有山西汾酒时，
    # 与之相关 0.79 的古井贡酒仍被排在买入计划第 1 位。
    held_rows = [r for r in rows if str(r["security_code"]).zfill(6) in holdings]
    returns = daily_returns_window(
        [str(r["security_code"]).zfill(6) for r in eligible]
        + [str(r["security_code"]).zfill(6) for r in held_rows])
    picked: list[dict] = []
    dropped: list[tuple[dict, float, str]] = []
    for cand in eligible[:SEC97_SCAN_DEPTH]:
        code = str(cand["security_code"]).zfill(6)
        worst, worst_name = 0.0, ""
        for held in held_rows + picked:
            if str(held["security_code"]).zfill(6) == code:
                continue                     # 加仓自身不与自己比
            value = pearson(returns, code, str(held["security_code"]).zfill(6))
            if value > worst:
                worst, worst_name = value, str(held.get("security_name", ""))
        if worst > SEC97_MAX_CORR:
            dropped.append((cand, worst, worst_name))
            continue
        picked.append(cand)

    # **可用资金 ≠ 净资产**（OI-062，2026-08-17 修）：满仓或带融资的账户里，净资产早已变成持仓市值，
    # 而买入只能用**现金＋未用授信**。此前这里以 `nav` 起算，会打印一份资金上不可能执行的计划——
    # 判例：2026-08-17 实际现金 535 元、负债 212.8 万，计划却显示「投入 49.5 万、余现金 235.0 万」。
    cash, plan, capped = (nav if funds is None else max(funds, 0.0)), [], []
    for cand in picked:
        price = to_float(cand.get("close")) or 0.0
        if price <= 0:
            continue
        code = str(cand["security_code"]).zfill(6)
        lot_amount = price * SEC97_LOT
        lots = int(tranche // lot_amount) if lot_amount <= tranche else 1
        cooldown = 0 if lot_amount <= tranche else round(lot_amount / tranche) - 1
        amount = lots * lot_amount
        if lots <= 0 or amount > cash:
            continue
        # 单票上限：**按「买入后」的市值判**，与回测 `--position-cap` 逐字同义。
        held_value = holdings.get(code, 0.0) * price
        if SEC97_POSITION_CAP and nav > 0 and (held_value + amount) / nav > SEC97_POSITION_CAP:
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
            "shares": lots * SEC97_LOT,
            "amount": round(amount, 2),
            "cooldown_skips": cooldown,
        })
    return {"plan": plan, "dropped": dropped, "eligible": eligible, "capped": capped,
            "frozen_out": frozen_out,
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
    print(f"\n§9.7 机械执行：`P/V ≤ {SEC97_BUY_LINE}` 的 {result['n_cheap']} 只；"
          f"再过走势条件的 **{len(result['eligible'])} 只**"
          f"（新建仓 `收>MA20>MA60`；**已持仓只须 `MA20>MA60`**，其中 {result['n_addon']} 只"
          f"是靠这条放宽进来的回踩加仓）；"
          f"§7.5 冻结硬排除 {len(result.get('frozen_out') or [])} 只；"
          f"相关性 >{SEC97_MAX_CORR} 剔除 {len(dropped)} 只 → 买入 {len(plan)} 只")
    for fz in result.get("frozen_out") or []:
        print(f"  [冻结排除·review_pending] {fz.get('security_name','')} P/V {fz['model_pv']:.2f}"
              f"（两闸已开，待 §6.7 重建解冻后按当日名次重入）")
    if result["n_held"] == 0:
        print("  ⚠ **没读到任何持仓**（data/processed/a_share_holdings.csv 缺失或为空）"
              "——加仓放宽会退回旧口径，买入计划不可直接照做")
    else:
        cap_txt = f"单票上限 {SEC97_POSITION_CAP:.0%}（只挡加仓、不强制减持）" if SEC97_POSITION_CAP else "单票无上限（v4.04 退役）"
        print(f"  持仓 {result['n_held']} 只已载入｜{cap_txt}")
    for cand, w in result["capped"]:
        print(f"  [单票上限挡下] {cand.get('security_name','')} "
              f"P/V {cand['model_pv']:.2f}｜现持仓已占净资产 {w:.1%}，再买一档将越过 "
              f"{SEC97_POSITION_CAP:.0%}")
    if result["funds_given"]:
        print(f"  一档 {result['tranche'] / 1e4:,.2f} 万｜**可用资金 {float(result['funds0']) / 1e4:,.2f} 万**"
              f"（现金＋未用授信）→ 投入 {invested / 1e4:,.2f} 万（占净资产 {invested / nav * 100:.1f}%）"
              f"｜余 {result['cash'] / 1e4:,.2f} 万")
    else:
        print(f"  一档 {result['tranche'] / 1e4:,.2f} 万｜⚠ **未给 `--funds`，按「可用资金＝净资产」估算**"
              f"（OI-062：满仓/带融资账户上此计划资金上不可执行，买入须走 §9.7.2 换仓）"
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


def main() -> int:
    args = parse_args()
    symbols = {item.strip().zfill(6) for item in args.symbols.split(",") if item.strip()} or None
    input_rows = load_csv(args.input)
    market_state = fetch_market_state(args.as_of, args.timeout)
    since = args.since
    if since == "auto":
        since = detect_last_scan(args.log_file, args.as_of)
        if since:
            print(f"§8.6 缺口回溯：检出上次扫描日 {since}，将回溯 {since}→{args.as_of} 区间")
        else:
            print("§8.6 缺口回溯：未检出上次扫描日，本次按单日快照执行")
    rows = scan(input_rows, args.as_of, symbols, args.timeout, args.workers, since)
    blocked = load_blocked_codes(args.review_queue)
    for row in rows:
        row["market_state"] = market_state
        # §8.12：弱势市场下各信号分级的操作偏向下调一档。
        if market_state == "弱势" and row.get("signal_state") == "buy_candidate":
            row["action_bias"] = "信号成立待确认" if row.get("signal_grade") == "强" else "等确认"
        # §8.13 入场阶段判定：弱势市场所需阶段整体上调一段；未达段位的候选只等不买。
        required = row.get("stage_required")
        if isinstance(required, int) and market_state == "弱势":
            required += 1
            row["stage_required"] = required
        stage = row.get("entry_stage") if isinstance(row.get("entry_stage"), int) else 0
        # §8.11.1 持续候选（v1.20）：所需段位在弱势市已上调，故达标日数在此处结算。
        stage_by_day = row.pop("stage_by_day", []) or []
        row["stage_met_days"] = (
            sum(1 for eff in stage_by_day if eff >= required) if isinstance(required, int) else 0
        )
        if row.get("signal_state") == "buy_candidate":
            if isinstance(required, int):
                if required > 4:
                    row["stage_met"] = False
                    row["action_bias"] = "弱势市需8.7.6平台二次确认（人工判定）"
                elif stage >= required:
                    row["stage_met"] = True
                else:
                    row["stage_met"] = False
                    row["action_bias"] = f"等入场阶段（已{stage}段/需{required}段）"
            else:
                row["stage_met"] = False
                row["action_bias"] = "当日档位组合无所需阶段映射，仅观察（数据核对）"
        # §7.5/§11.9 复核期买入冻结：有信号也不列买入候选。
        if blocked and row.get("signal_state") == "buy_candidate" and str(row.get("security_code", "")).zfill(6) in blocked:
            row["signal_state"] = "buy_blocked_review_pending"
            row["action_bias"] = "复核完成前冻结买入（§7.5）"
        # §8.11.1 持续候选置顶提醒（v1.20）：持续达标 × 反复新触发 × 未转弱。
        # 判例特宝生物 2026-07-15→07-27：连续 8 日 buy_candidate、段位全程达标、期间 4 日新触发，
        # 但 5 日为弱级，按 §9.3「弱级只汇总只数」在阅读版日志中不可见。本标只解决可见性，
        # 不改变分级/优先级/入场阶段/买入资格。持仓的排除在 §9.2 组稿时执行（第一节已逐只可见）。
        row["persistent_candidate"] = bool(
            row.get("signal_state") == "buy_candidate"
            and row.get("stage_met") is True
            and row.get("stage_met_days", 0) >= PERSIST_STAGE_MET_DAYS
            and row.get("stage_trigger_days", 0) >= PERSIST_TRIGGER_DAYS
            and row.get("trend_strength") != "weakening"
        )
        # §9.6 深度低估重点关注（v2.01 立，v2.11 重定门槛）。与 §8.11.1 同型：只解决可见性，
        # 不改任何判定。三个条件——①足够便宜（`deep_value_cheap`，两层口径不同见其定义）；
        # ②有止跌企稳证据（任一 §8.7 信号，含弱级；或 §8.7.9 前置状态；或 §8.7.10/§8.7.12
        # 观察标记）；③未在放量下跌/缩量阴跌中。第③条是必要的：深度低估 + 仍在下跌 = 尚未
        # 止跌，那是「继续等」不是「可以关注了」。
        stab = row.pop("stabilizing", False)
        row["deep_value_watch"] = bool(
            deep_value_cheap(row)
            and (stab or row.get("signals") or row.get("observation_tags"))
            and row.get("trend_strength") != "weakening"
        )
    fieldnames = [
        "trade_date",
        "security_code",
        "security_name",
        "exchange",
        "quality_tier",
        "quality_tier_label",
        # §9.2.1 参考分（v2.14）：池 CSV 已随 signal.update(pool_row) 带进来，这里只是把它写出去。
        # 仅供报告显示同档内排序，不参与矩阵资格、段位与优先级的任何判定。
        "quality_score",
        "pool_layer",
        "valuation_tier",
        "valuation_tier_effective",
        "valuation_tier_changed",
        # 合理价区间随行透出（v2.11）：§9.6 的完整名单必须列出「合理价区间」，
        # 缺这两列就得回头再拼一次池 CSV，组稿时容易拼错行。
        "fair_price_low",
        "fair_price_high",
        "band_position",
        "margin_of_safety",
        # §9.7 用的模型带三列（结 OI-051）。**与 fair_price_low/high 并存不混用**：
        # 前者是逐票档案带、供 §6.2.1.6 自动定档；这三列是批量模型带、供 §9.7 买入判定。
        "model_intrinsic_value",
        "model_band_source",
        "model_pv",
        "deep_value_watch",
        "strategy_tag",
        "total_market_cap_bn",
        "market_cap_now_yi",
        "signal_state",
        "priority",
        "action_bias",
        "signal_grade",
        "entry_stage",
        "entry_stage_today",
        "stage_required",
        "stage_met",
        "stage_met_days",
        "stage_trigger_days",
        "persistent_candidate",
        "megacap_volume",
        "trend_strength",
        "market_state",
        "signals",
        "observation_tags",
        "gap_trading_days",
        "gap_return",
        "gap_max_vol_ratio",
        "gap_max_vol_day",
        "gap_signal_days",
        "gap_signals_fired",
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
        "ma150",
        "ma250",
        "amount_ma20",
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
        "long_term_confirm",
        "break_periods",
        "overextended",
        "data_source",
        "screened_at_utc",
    ]
    # §9.7 的 P/V **必须在落盘之前挂上**：`fieldnames` 里已经声明了那三列，
    # 若等落盘后再算，写出去的就是三列空值——正是本文件 §9.2.1 校验段警告的
    # 「某列整体为空而无人察觉」。首版就踩了这一脚，靠落地校验（下方 priced 计数）当场发现。
    section97_ready = bool(args.model_bands and args.model_bands.exists())
    if section97_ready:
        bands = load_model_bands(args.model_bands, args.as_of)
        attach_model_pv(rows, bands, args.as_of, args.rf)
        priced = sum(1 for r in rows if isinstance(r.get("model_pv"), float))
        print(f"§9.7 模型带：{len(bands)} 只有带，{priced}/{len(rows)} 只算出 P/V"
              f"（银行走股利折现 rf={args.rf:.4%}+{BANK_RISK_PREMIUM:.0%}）")
        if priced < len(rows):
            missing = [str(r.get("security_name", "")) for r in rows
                       if not isinstance(r.get("model_pv"), float)][:8]
            print(f"  **无带 {len(rows) - priced} 只**（§9.7 判定不到它们）：{'、'.join(missing)}")
        if rows and not priced:
            print("  **告警：model_pv 整列为空** —— 模型带与池对不上号，§9.7 本次等于没跑")
    write_csv(args.output_csv, rows, fieldnames)
    review_note = (
        "复核冻结：已启用（读取更新队列）。" if blocked is not None else
        "复核冻结：未启用（更新队列文件缺失，§7.5 冻结未生效）。"
    )
    log_scan_decisions(args.log_file, rows, args.as_of, args.input, args.output_csv)
    print(f"scanned {len(rows)} rows from {args.input}; market_state={market_state}; {review_note}")

    # §9.6 落地校验（§15.2 第 2 条：新规则须同时给出跑批时可见的命中数，否则又是一条空文）。
    # 同时打印「够便宜但没止跌」的只数——那是本规则**有意排除**的一类，不打印就看不出第③条在起作用。
    deep = [r for r in rows if r.get("deep_value_watch")]
    cheap = [r for r in rows if deep_value_cheap(r)]
    weak_only = [r for r in cheap if not r.get("deep_value_watch")]
    print(f"[盘面描述·不进 §9.7 判定] 深度低估重点关注：命中 {len(deep)} 只"
          f"（空间过门槛 {len(cheap)} 只，其中 {len(weak_only)} 只未见止跌/仍在下跌被排除）")
    # 全量打印，不截断（v2.11）：§9.2 第二节要求给出完整名单与逐只信息，
    # 这里少打一只，组稿时就无从知道它存在过。
    for r in sorted(deep, key=lambda x: -x["margin_of_safety"]):
        grade = r.get("signal_grade") or "无级"
        low, high = r.get("fair_price_low") or "—", r.get("fair_price_high") or "—"
        # `pct_chg` 已是百分数（+3% 存为 3.0），`ret_5d` 是比率（+3% 存为 0.03）——两列单位不同，
        # 同一行并排打印必须先归一，否则 5 日涨幅会显示成 1/100。
        pct, ret5 = r.get("pct_chg"), r.get("ret_5d")
        pct_s = f"{float(pct):+.2f}%" if isinstance(pct, (int, float)) else "—"
        ret5_s = f"{float(ret5) * 100:+.2f}%" if isinstance(ret5, (int, float)) else "—"
        print(f"    {r.get('quality_tier','')[:2]}×{r.get('valuation_tier_effective','')}"
              f" {r.get('security_name','')}"
              f"｜现价 {r.get('close','—')}｜带 {low}-{high}｜空间 {r['margin_of_safety'] * 100:.0f}%"
              f"｜当日 {pct_s}｜5日 {ret5_s}"
              f"｜{grade}｜{r.get('trend_strength','')}"
              f"｜{(r.get('signals') or r.get('observation_tags') or '仅平台企稳前置')[:46]}")

    # §9.2.1 落地校验：新增列跑完必须核对非空行数——§15.2 第 3 条四次复发的共同签名
    # 就是「某列整体为空而无人察觉」，而报告一旦改用手填值就再也发现不了。
    scored = [r for r in rows if str(r.get("quality_score", "")).strip()]
    print(f"参考分（工作流 §5.7）非空 {len(scored)}/{len(rows)} 行")
    if rows and not scored:
        print("**告警：quality_score 整列为空** —— 池 CSV 未透传参考分，报告不得手填，先修池物化")

    # §9.7 的买入计划（`attach_model_pv` 已在落盘前跑过，见上文）。
    if section97_ready:
        if args.nav > 0:
            report_section97(section97_entry_plan(rows, args.nav, args.funds, load_holdings(),
                                                  blocked or set()),
                             args.nav, args.plan_out, args.as_of)
        else:
            print("§9.7 未给 --nav，只算 P/V 不出买入计划（一档以净资产为基数）")
    else:
        print(f"§9.7 机械执行层未运行：模型带文件不存在（{args.model_bands}）。"
              f"重建见 §6.5.7.1；不跑它则本次只产出 §8 的取数与信号，**买入判定缺席**")

    return data_error_exit_code(rows)


DATA_ERROR_ABORT_RATIO = 0.5


def data_error_exit_code(rows: list[dict]) -> int:
    """行情整体取不到时必须非 0 退出（§15.2 第 3 条「静默失效」）。

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
        sample = "; ".join(str(r.get("wait_reasons", ""))[:80] for r in failed[:3])
        print(f"⚠️ {len(failed)}/{len(rows)} 行取数失败（{ratio:.0%} ≥ {DATA_ERROR_ABORT_RATIO:.0%}）"
              f"——判定为系统性行情故障，本次扫描结果不可用。样例：{sample}", file=sys.stderr)
        return 1
    if failed:
        print(f"注意：{len(failed)}/{len(rows)} 行取数失败（低于 {DATA_ERROR_ABORT_RATIO:.0%} 阈值，按个别停牌处理）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
