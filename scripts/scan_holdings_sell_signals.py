#!/usr/bin/env python3
"""Scan A-share holdings for stop-loss, valuation-sell, and trend-sell actions.

Deterministic part of operation-workflow Stage 5 (§14 卖出许可, v1.12; trend split
v1.19, graduation tightened v1.21): stop-loss hit (Tier-0), valuation-sell
eligibility (effective tier 较高估/高估 per §6.2.1.6 computed from the pool's fair
band, with the keep-floor amount = position value minus build_amount_cny),
major-trend deterioration under the two-state reference (§14 — trend-state
positions: close below MA60/MA120; reversal/base-state positions, i.e. the §8.6
mid-term bullish alignment `close > MA20 > MA60 > MA120` never yet reached since
first entry: close below the launch structure anchor `launch_platform_price` or
MA20; a sell PERMISSION, not an order), valuation-tier refresh against the core
pool, and account drawdown/leverage alerts from the account snapshot. Stop prices
are user-set at entry and never adjusted or suggested by the system (v1.11).
Lockup, profit ladders, and the three-tier trend-protection lines are retired
(v1.12); the holding-period single-trade-risk alert and passive weight-drift
warnings are retired (v1.21 — both can only fire on price appreciation, so they
warn on winners rather than on risk; the entry-time 1.5%N check in §13.6 and the
active-side structural caps in the §10 gate are untouched). It does NOT decide hard
falsification (veto / sudden event / severe quarterly miss / verified structural
thesis break); those are left to model judgment per the workflow's script/LLM
split (§14).
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

from a_share_quotes import quote_symbol
from workflow_decision_log import WORKFLOW_VERSION, append_decision_log


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_VALUATION_POOL = ROOT / "data/processed/a_share_core_valuation_pool.csv"
DEFAULT_ACCOUNT_SNAPSHOT = ROOT / "data/processed/portfolio_account_snapshot.csv"
DEFAULT_OUTPUT_CSV = ROOT / "data/processed/daily_holdings_actions.csv"
DEFAULT_DECISION_LOG = ROOT / "data/processed/a_share_workflow_decision_log.csv"
EASTMONEY_KLINE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
# 统一走腾讯 newfqkline（与 screen_daily_volume_price_signals.py 同口径）：同构覆盖 sh/sz/bj，
# 且为北交所唯一可用历史K线源；旧 web.ifzq 端点批量易限流且 qfq 序列收盘后滞后无补齐。
TENCENT_KLINE = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

BASE_BUILD_AMOUNT = 250_000  # 25 万元
SINGLE_STOCK_WEIGHT_LIMIT = 0.30  # §13 第 8 条单票红线；v1.21 起仅为审计事实位（被动漂移不预警）
# 个人体系 §13.1 回撤预算：自净值峰值 -8% 去杠杆 / -12% 黄色 / -20% 红色。
DRAWDOWN_TIERS = ((0.20, "红色警告"), (0.12, "黄色警告"), (0.08, "去杠杆"))
# §6.2.1.6 价格自动定档（估值卖出资格用）：带顶 1.2 倍以上=高估；带底以下按空间分低估/较低估。
OVERVALUED_MULT = 1.2
DEEP_UNDERVALUED_SPACE = 0.40
VALUATION_SELL_TIERS = {"较高估", "高估"}
# §14 大趋势走坏（v1.19 分态）：趋势态持仓收盘跌破 MA60/MA120 触发趋势卖出许可；
# 反转/筑底态持仓（首次建仓日收盘 < 当日MA120，未毕业）改按启动结构锚/MA20 判定。
TREND_WINDOWS = (60, 120)
TREND_STATE_TREND = "趋势态"
TREND_STATE_REVERSAL = "反转/筑底态"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def load_valuation_pool(path: Path) -> dict[str, dict[str, str]] | None:
    """Core valuation pool keyed by code; None when the file is unavailable (§14 输入 4)."""
    if not path.exists():
        return None
    return {row["security_code"].zfill(6): row for row in load_csv(path) if row.get("security_code")}


def load_account_snapshot(path: Path) -> dict[str, str] | None:
    """Latest row of the append-style account snapshot (§14 输入 7).

    Ties on as_of resolve to the LAST appended row: same-day rows are corrections
    that supersede earlier ones (e.g. a broker-exact row replacing an estimate).
    `max()` alone would keep the first, silently ignoring the correction.
    """
    if not path.exists():
        return None
    rows = load_csv(path)
    if not rows:
        return None
    latest = max(row.get("as_of", "") for row in rows)
    return [row for row in rows if row.get("as_of", "") == latest][-1]


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
    # 北交所（92/43/83/87 前缀）：东财K线无数据，直接走腾讯 newfqkline。
    if quote_symbol(code, exchange).startswith("bj"):
        return fetch_daily_tencent(code, exchange, as_of, timeout)
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
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "ignore"))
    except OSError:
        return fetch_daily_tencent(code, exchange, as_of, timeout)
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return fetch_daily_tencent(code, exchange, as_of, timeout)
    dates = [line.split(",")[0] for line in klines]
    closes = [float(line.split(",")[2]) for line in klines]
    return url, dates, closes


def fetch_daily_tencent(code: str, exchange: str, as_of: str, timeout: float) -> tuple[str, list[str], list[float]]:
    """后备源：腾讯前复权日线（与 screen_daily_volume_price_signals.py 同口径，走 newfqkline）。"""
    symbol = quote_symbol(code, exchange)
    param = f"{symbol},day,2020-01-01,{as_of},1000,qfq"
    url = f"{TENCENT_KLINE}?param={param}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    data = (payload.get("data") or {}).get(symbol) or {}
    klines = data.get("qfqday") or data.get("day") or []
    dates = [str(row[0]) for row in klines]
    closes = [float(row[2]) for row in klines]
    # 腾讯前复权序列收盘后可能滞后一个交易日：用不复权序列补齐最新K线（最新bar的qfq值=不复权值）。
    if dates and dates[-1] < as_of:
        raw_url = f"{TENCENT_KLINE}?param={symbol},day,{dates[-1]},{as_of},10,"
        raw_request = urllib.request.Request(
            raw_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
        )
        try:
            with urllib.request.urlopen(raw_request, timeout=timeout) as response:
                raw_data = (json.loads(response.read().decode("utf-8", "ignore")).get("data") or {}).get(symbol) or {}
        except OSError:
            raw_data = {}
        for parts in raw_data.get("day") or []:
            if str(parts[0]) > dates[-1]:
                dates.append(str(parts[0]))
                closes.append(float(parts[2]))
        url = f"{url};{raw_url}"
    return url, dates, closes


def moving_average(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def mid_term_bullish_alignment(closes: list[float], index: int) -> bool:
    """§8.6 中期多头排列（v1.21）：close > MA20 > MA60 > MA120。均线排列是慢变量，
    单日价格穿越 MA120 不构成成立；上市不足 120 日无 MA120 者恒不成立。"""
    if index + 1 < 120:
        return False
    ma20 = sum(closes[index - 19 : index + 1]) / 20
    ma60 = sum(closes[index - 59 : index + 1]) / 60
    ma120 = sum(closes[index - 119 : index + 1]) / 120
    return closes[index] > ma20 > ma60 > ma120


def classify_trend_state(dates: list[str], closes: list[float], entry_date: str) -> str:
    """§14 v1.21 持仓趋势参照分态：首次建仓日 §8.6 中期多头排列不成立 → 反转/筑底态；
    自建仓后任一交易日中期多头排列成立即毕业转趋势态（不可逆）。原 v1.19「任一收盘
    > 当日MA120 即毕业」已废止——单日穿越不等于反转完成，会使底部仓冲高即转趋势态、
    次日正常回调便报趋势走坏（紫金矿业/宁德时代/小商品城 2026-07-29 判例）。上市不足
    120 日无 MA120 的按反转态处理；无建仓日记录时保守沿用趋势态。"""
    if not entry_date:
        return TREND_STATE_TREND
    start = next((i for i, d in enumerate(dates) if d >= entry_date), None)
    if start is None:
        return TREND_STATE_TREND
    for i in range(start, len(closes)):
        if mid_term_bullish_alignment(closes, i):
            return TREND_STATE_TREND  # 建仓日成立=趋势态建仓；之后成立=毕业（不可逆）
    return TREND_STATE_REVERSAL


def effective_valuation_tier(close: float, band_low: float | None, band_high: float | None) -> str:
    """§6.2.1.6 价格自动定档（双向不限幅，v1.14）；无带（无法估值/出池）返回空串，不自动定档。"""
    if not band_low or not band_high or band_low <= 0 or band_high <= 0:
        return ""
    if close > band_high * OVERVALUED_MULT:
        return "高估"
    if close > band_high:
        return "较高估"
    if close >= band_low:
        return "中性"
    mid = (band_low + band_high) / 2
    return "低估" if mid / close - 1 >= DEEP_UNDERVALUED_SPACE else "较低估"


def classify_holding(
    row: dict[str, str], as_of: date, timeout: float, pool: dict[str, dict[str, str]] | None
) -> dict[str, object]:
    code = (row.get("security_code") or "").zfill(6)
    result: dict[str, object] = {key: row.get(key, "") for key in row}
    result["security_code"] = code

    # §14 持仓估值档位刷新：对照最新核心池；池不可用时标注未刷新。
    band_low: float | None = None
    band_high: float | None = None
    pool_row: dict[str, str] | None = None
    if pool is None:
        result["pool_valuation_tier"] = ""
        result["valuation_alert"] = "估值池文件缺失，未刷新档位"
    else:
        pool_row = pool.get(code)
        if pool_row is None:
            result["pool_valuation_tier"] = "不在核心估值合格池"
            result["valuation_alert"] = "已出池（高估/无法估值/降档），按§14风险预警5复核"
        else:
            band_low = to_float(pool_row.get("fair_price_low"))
            band_high = to_float(pool_row.get("fair_price_high"))
            pool_tier = pool_row.get("valuation_tier", "")
            result["pool_valuation_tier"] = pool_tier
            held_tier = (row.get("valuation_tier") or "").strip()
            held_norm = held_tier.split("(")[0].split("（")[0].strip()
            result["valuation_alert"] = (
                f"档位变化：持仓记录[{held_tier}] -> 最新池[{pool_tier}]"
                if held_norm and pool_tier and held_norm != pool_tier
                else ""
            )

    cost = to_float(row.get("cost_basis"))
    stop = to_float(row.get("stop_loss_price"))
    build_amount = to_float(row.get("build_amount_cny")) or 0.0
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

    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma120 = moving_average(closes, 120)
    profit_pct = (close / cost - 1) if cost else None
    position_value = (current_shares or 0.0) * close

    # §14 大趋势走坏（v1.19 分态）：趋势态对照 MA60/MA120；反转/筑底态对照启动结构锚+MA20。
    trend_state = classify_trend_state(dates, closes, (row.get("entry_date") or "").strip())
    launch = to_float(row.get("launch_platform_price"))
    structure_broken = False
    if trend_state == TREND_STATE_TREND:
        broken = [f"MA{w}" for w, ma in zip(TREND_WINDOWS, (ma60, ma120)) if ma is not None and close < ma]
        trend_deterioration = "跌破" + "+".join(broken) if broken else ""
        trend_detail = "、".join(
            f"{name}≈{round(ma, 2)}" for name, ma in zip(("MA60", "MA120"), (ma60, ma120)) if ma is not None
        )
    else:
        broken = []
        if launch is not None and close < launch:
            broken.append("启动结构")
            structure_broken = True
        if ma20 is not None and close < ma20:
            broken.append("MA20")
        trend_deterioration = "反转态跌破" + "+".join(broken) if broken else ""
        trend_detail = "、".join(
            part
            for part in (
                f"启动结构锚≈{launch}" if launch is not None else "",
                f"MA20≈{round(ma20, 2)}" if ma20 is not None else "",
            )
            if part
        )

    # §14 估值卖出资格（v1.12）：现档较高估/高估，可卖金额=市值−建仓金额（留底原则）。
    eff_tier = effective_valuation_tier(close, band_low, band_high)
    # §9.2 持仓健康度表带位列（v1.15）：与池扫描同口径（越带顶+X% / 低于带底-X% / 带内X%）。
    band_position = ""
    if band_low and band_high and band_low > 0 and band_high > 0:
        if close > band_high:
            band_position = f"越带顶+{(close / band_high - 1) * 100:.0f}%"
        elif close < band_low:
            band_position = f"低于带底-{(1 - close / band_low) * 100:.0f}%"
        else:
            pos = (close - band_low) / (band_high - band_low) * 100 if band_high > band_low else 0.0
            band_position = f"带内{pos:.0f}%"
    valuation_sell = eff_tier in VALUATION_SELL_TIERS
    # v1.39：估值卖出资格必须与池的三态口径同源。池已按 §6.5.5.1 与 §6.5.4 抑制两类
    # 卖出提醒——下限带（明确不含成长/管线/订单价值）与周期假设未决（「贵」取决于
    # 未取得的供给侧证据）——本处此前独立重算，导致同一只票池判可持有、卖出扫描判
    # 可卖（判例：紫金矿业、神火股份 2026-08-01）。
    suppress_reason = ""
    if valuation_sell and pool_row:
        if str(pool_row.get("band_is_floor", "")).strip().lower() == "true":
            suppress_reason = "下限带（§6.5.5.1：明确不含未兑现价值，反向读作『贵』不成立）"
        elif pool_row.get("cycle_assumption") == "mean_reversion_assumed":
            suppress_reason = "周期假设未决（§6.5.4：中枢锚假设均值回归，运行率显著更高）"
    if suppress_reason:
        valuation_sell = False
    # §14 v1.27 减仓梯（v1.39 落地）：原「留底原则（剩余市值 ≥ 建仓金额）」已于 v1.27
    # 废止——它是卖出规则最后一个成本锚，与「卖出只由估值决定、与盈亏无关」抵触。
    # 脚本此前仍按旧口径算，两只可卖持仓均得出「可卖约 0」。现改为按档分级的减仓梯：
    # 台阶 {M, H, 1.2H, 1.44H}，每跨一阶减**剩余股数**的 20%，1.44H 起 40%。
    trim_pct, trim_step = 0.0, ""
    if valuation_sell and band_low and band_high:
        mid = (band_low + band_high) / 2
        steps = [("M", mid), ("H", band_high), ("1.2H", band_high * 1.2), ("1.44H", band_high * 1.44)]
        tier_key = ((pool_row or {}).get("quality_tier") or row.get("quality_tier") or "").strip().upper()
        start = {"L1": 2, "L2": 1, "L3": 0}.get(tier_key, 1)
        crossed = [(name, level) for i, (name, level) in enumerate(steps) if i >= start and close >= level]
        if crossed:
            trim_step = crossed[-1][0]
            trim_pct = 0.40 if trim_step == "1.44H" else 0.20
    valuation_sell_amount = position_value * trim_pct

    # Deterministic action priority (forced_exit is decided by the model, not here).
    if stop is not None and close <= stop:
        action, reason = "stop_loss_sell", f"现价 {close} <= 割肉价 {stop}，无条件清仓（当日/次日执行）"
    elif broken:
        action = "trend_sell_allowed"
        if trend_state == TREND_STATE_TREND:
            label = "大趋势走坏"
        elif structure_broken:
            label = "反转态走坏·结构档（右侧事实失效，§8.13.4）"
        else:
            label = "反转态走坏·短期档"
        reason = f"{label}：收盘 {close} {trend_deterioration}（{trend_detail}），允许减仓乃至清仓（许可非指令，人工核对后执行）"
        if valuation_sell:
            reason += f"；同时现档{eff_tier}具估值卖出资格"
    elif valuation_sell:
        action = "valuation_sell_eligible"
        reason = (
            f"现档{eff_tier}（收盘 {close} vs 合理价区间 {band_low}-{band_high}）；§14 减仓梯已跨至 "
            f"{trim_step} 台阶 → 提醒减持**剩余股数的 {trim_pct:.0%}**，约 {valuation_sell_amount:,.0f} 元"
            f"（按剩余股数递减、永不清仓，天然形成底仓；提醒非指令，防抖需连续 3 日维持）"
        )
    elif suppress_reason:
        action = "hold"
        reason = (f"现档{eff_tier}本会触发估值卖出，但按 {suppress_reason} 抑制——"
                  f"该带不足以支撑卖出结论，须先补齐相应证据")
    else:
        action, reason = "hold", "无卖出许可触发（割肉/估值/趋势均未触发）"

    result.update(
        {
            "as_of": as_of.isoformat(),
            "close": round(close, 3),
            "cost_basis": cost if cost is not None else "",
            "profit_pct": round(profit_pct, 4) if profit_pct is not None else "",
            "stop_loss_price": stop if stop is not None else "",
            "stop_hit": bool(stop is not None and close <= stop),
            "ma20": round(ma20, 3) if ma20 is not None else "",
            "ma60": round(ma60, 3) if ma60 is not None else "",
            "ma120": round(ma120, 3) if ma120 is not None else "",
            "trend_ref_state": trend_state,
            "trend_deterioration": trend_deterioration,
            "effective_valuation_tier": eff_tier,
            "band_position": band_position,
            "valuation_sell_eligible": valuation_sell,
            "valuation_sell_allowed_amount": round(valuation_sell_amount, 2) if valuation_sell else "",
            "sell_floor_amount": build_amount if build_amount else "",
            "initial_shares": initial_shares,
            "current_shares": current_shares,
            "cumulative_trim_pct": cumulative_trim,
            "position_value": round(position_value, 2),
            "holdings_action": action,
            "action_reason": reason,
            "forced_exit_review": "pending_model_review",
            "data_source": data_source,
            "scanned_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    return result


def add_weights(rows: list[dict[str, object]], snapshot: dict[str, str] | None) -> dict[str, object]:
    """权重、build_amount、账户回撤/杠杆状态与单笔风险校验（§13/§14，个人体系 §13.1/§13.2）。

    总资产 = 全部持仓市值 + 账户快照现金（原则上不持现金，但快照记有余额时必须计入，
    否则净资产被系统性低估、回撤被高估）；净资产 = 总资产 - 融资负债（均取快照最新行）。
    结构占比与单票权重仍按持仓市值计（§13 第 3 条，杠杆与现金中性）。
    """
    valid_rows = [r for r in rows if r.get("holdings_action") != "data_error"]
    holdings_value = sum(float(r.get("position_value") or 0.0) for r in valid_rows)
    cash = to_float((snapshot or {}).get("cash_cny")) or 0.0
    total = holdings_value + cash
    quotes_ok = bool(valid_rows) or not rows
    margin_debt = to_float((snapshot or {}).get("margin_debt_cny")) or 0.0
    recorded_peak = to_float((snapshot or {}).get("account_peak_net_assets_cny"))
    net_assets = max(total - margin_debt, 0.0) if snapshot else total
    peak = max(recorded_peak or 0.0, net_assets)
    if not quotes_ok:
        drawdown = 0.0
        drawdown_status = "数据异常（行情不可用），未计算"
    else:
        drawdown = (1 - net_assets / peak) if peak > 0 else 0.0
        drawdown_status = "正常"
        for threshold, label in DRAWDOWN_TIERS:
            if drawdown >= threshold:
                drawdown_status = label
                break
    leverage = total / net_assets if net_assets > 0 else 0.0
    guarantee_pct = total / margin_debt * 100 if margin_debt > 0 else 0.0

    for row in rows:
        value = float(row.get("position_value") or 0.0)
        weight = value / holdings_value if holdings_value else 0.0
        row["current_weight_pct"] = round(weight * 100, 2)
        # §13 第 8 条被动口径（v1.21）：本列降为审计事实位，被动上涨越限不预警、不建议减仓；
        # 主动越限（新建仓/加仓）由 §10 闸门第 11 项在买入前拦截，不经本脚本。
        row["weight_over_limit"] = bool(weight > SINGLE_STOCK_WEIGHT_LIMIT)
        # 单笔风险持仓监控值：§14 风险预警 4 已于 v1.21 退役（该值 = 持股数×(现价−割肉价)÷净资产，
        # 是现价的单调增函数，只可能因上涨触发），保留数值为审计字段，不再置 over_limit 标记。
        # 建仓时的 1.5%N 校验（§13 第 6 条）仍是买入前置硬条件，在 §10 闸门环节完成。
        close = to_float(row.get("close"))
        stop = to_float(row.get("stop_loss_price"))
        if close and stop and close > stop and net_assets > 0:
            risk = value * (close - stop) / close / net_assets
            row["single_trade_risk_pct"] = round(risk * 100, 2)
        else:
            row["single_trade_risk_pct"] = ""
        row["single_trade_risk_over_limit"] = False

    return {
        "total_assets": total,
        "holdings_value": holdings_value,
        "cash": cash,
        "snapshot_available": snapshot is not None,
        "snapshot_as_of": (snapshot or {}).get("as_of", ""),
        "margin_debt": margin_debt,
        "net_assets": net_assets,
        "peak_net_assets": peak,
        "drawdown_pct": drawdown,
        "drawdown_status": drawdown_status,
        "leverage": leverage,
        "guarantee_pct": guarantee_pct,
    }


def scan(
    rows: list[dict[str, str]],
    as_of: date,
    symbols: set[str] | None,
    timeout: float,
    workers: int,
    pool: dict[str, dict[str, str]] | None,
) -> list[dict[str, object]]:
    eligible = [r for r in rows if r.get("security_code") and (not symbols or r["security_code"].zfill(6) in symbols)]
    if not eligible:
        return []
    by_code: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(classify_holding, r, as_of, timeout, pool): r["security_code"].zfill(6) for r in eligible}
        for future in as_completed(futures):
            by_code[futures[future]] = future.result()
    return [by_code[r["security_code"].zfill(6)] for r in eligible if r["security_code"].zfill(6) in by_code]


def log_decisions(log_file: Path, rows: list[dict[str, object]], as_of: date, holdings_file: Path, output_csv: Path) -> None:
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
            "output_file": str(output_csv),
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
    parser.add_argument("--valuation-pool", type=Path, default=DEFAULT_VALUATION_POOL,
                        help="Core valuation pool CSV for refreshing holding valuation tiers (§14 输入 4).")
    parser.add_argument("--account-snapshot", type=Path, default=DEFAULT_ACCOUNT_SNAPSHOT,
                        help="Append-style account snapshot CSV for drawdown/leverage alerts (§14 输入 7).")
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    parser.add_argument("--symbols", default="", help="Optional comma-separated security codes to filter holdings.")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=8)
    return parser.parse_args()


FIELDNAMES = [
    "as_of", "security_code", "security_name", "strategy_tag", "quality_tier", "valuation_tier",
    "position_status", "pool_valuation_tier", "valuation_alert",
    "entry_date", "cost_basis", "close", "profit_pct",
    "stop_loss_price", "stop_hit", "ma20", "ma60", "ma120", "trend_ref_state", "trend_deterioration",
    "effective_valuation_tier", "band_position", "valuation_sell_eligible", "valuation_sell_allowed_amount",
    "sell_floor_amount",
    "initial_shares", "current_shares", "cumulative_trim_pct",
    "position_value", "current_weight_pct", "weight_over_limit",
    "single_trade_risk_pct", "single_trade_risk_over_limit",
    "holdings_action", "action_reason", "forced_exit_review", "data_source", "scanned_at_utc",
]


def main() -> None:
    args = parse_args()
    as_of = date.fromisoformat(args.as_of)
    symbols = {item.strip().zfill(6) for item in args.symbols.split(",") if item.strip()} or None
    holdings = load_csv(args.holdings) if args.holdings.exists() else []
    pool = load_valuation_pool(args.valuation_pool)
    snapshot = load_account_snapshot(args.account_snapshot)
    rows = scan(holdings, as_of, symbols, args.timeout, args.workers, pool)
    account = add_weights(rows, snapshot)
    write_csv(args.output_csv, rows, FIELDNAMES)
    if rows:
        log_decisions(args.log_file, rows, as_of, args.holdings, args.output_csv)
    print(
        f"scanned {len(rows)} holdings; total_assets={account['total_assets']:,.0f}; "
        f"net_assets={account['net_assets']:,.0f}; cash={account['cash']:,.0f}; "
        f"drawdown={account['drawdown_pct']:.1%} ({account['drawdown_status']}); "
        f"leverage={account['leverage']:.2f}x; guarantee={account['guarantee_pct']:.0f}%"
    )


if __name__ == "__main__":
    main()
