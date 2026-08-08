#!/usr/bin/env python3
"""OI-034 第 2/3 步：估值组与走势组回测，含逐周期与组合层指标。

规格来自用户 2026-08-07 与 2026-08-08 两次指令，逐条照录并标明本脚本对含糊处的取值
（**凡本脚本自行定义的规则都在下面列出，须用户确认**）：

| 用户原述 | 本脚本实现 |
| --- | --- |
| 「每天对所有股票按空间排序，买入空间最大的前十个」 | 每个交易日重排；**先筛后排**——合格集 `P/V ≤ 0.9`，只在合格集内排序 |
| 「合格集为空时持币」（2026-08-08 裁定） | 当日不买，现金留存；**不硬凑前十** |
| 「每次买入总仓位的 x%」 | 每次买入金额 = **当日总资产 × x%**，逐票独立 |
| 「卖出…每次卖出总资金的 x%」 | 触发 `P/V ≥ 1.1` 时卖出 **当日总资产 × x%** 的市值，不足则清空该票 |
| 「趋势满足条件时一笔买入」 | **本脚本定义**：`收盘 > MA20` 且 `MA20 > MA60`，同时 `P/V ≤ 0.9` |
| 「买入日的 20 日均线为止损价」 | 记录建仓日 MA20，收盘跌破即**全部清仓** |
| 「成交按当日收盘价」 | 是；不计手续费与冲击成本（**故结果是上界**） |
| 「初始 300 万」 | 是；**不允许融资**，现金不足则少买或不买 |

**分红送转必须落到账上，否则回测直接是错的**：持仓穿越 10 转 10 而不调股数，会凭空亏
一半；现金分红不入账则系统性低估收益。本脚本在除权日按
`股数 ×= (1 + 送转比)`、`现金 += 除权前股数 × 每股现金红利` 处理。

**两处结构性偏误，读数前必须知道（不是本脚本能修的）**：

1. **幸存者偏差 + 选样前视**。回测标的是**今日的 261 只池内股票**，而池由 2026 年的分层
   与建档选出。实测 2000-01-01 时这 261 只中**仅 34 只在市**（13%）、2005 年也只有 67 只
   （26%）。**回测起点越早，两种偏误越重**——2000 年起跑等于「买入我在 2026 年已知仍然
   优秀的那 34 只」，那不是策略检验而是同义反复。故结果按年代分段呈现，早期段只可当
   上界读。
2. **不计交易成本**。A 股双边约 0.1~0.2%（含印花税），高换手参数（大 x、日频）受影响远
   大于低换手参数，**故 x 之间的比较对 x 大的一侧不利**。

用法::

    python3 scripts/backtest_valuation_strategy.py --x 1 0.5 0.1 --since 2016-01-01
    python3 scripts/backtest_valuation_strategy.py --strategy trend --x 1
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DAILY_STATES = ROOT / "data/processed/a_share_historical_valuation_daily.csv"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
RATES = ROOT / "data/reference/cost_of_equity_inputs.csv"
BENCHMARK = ROOT / "data/raw/ohlcv/INDEX_000300.csv"
OUT_DIR = ROOT / "data/processed/backtest"

INITIAL_CAPITAL = 3_000_000.0
BUY_RATIO_MAX = 0.90      # 合格：P/V ≤ 0.9
SELL_RATIO_MIN = 1.10     # 触发减持：P/V ≥ 1.1
MAX_POSITIONS = 10
TRADING_DAYS = 244

# 安全边际按档位（§6.5.7.1.1：风险惩罚归决策层，不塞进 r）。**只作用于买入线。**
MOS_BY_TIER = {"L1": 0.10, "L2": 0.20, "L3": 0.30}
DEFAULT_TIER = "L2"


def _num(text: str | None) -> float | None:
    try:
        return float((text or "").strip())
    except ValueError:
        return None


# ------------------------------------------------------------------ 载入
def load_states() -> dict[str, list[tuple[str, float, float, float]]]:
    """{日期: [(代码, 收盘, 内在价值, P/V), …]}——已按送转折算过的口径。"""
    out: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    with DAILY_STATES.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out[row["date"]].append((row["security_code"], float(row["close"]),
                                     float(row["intrinsic_value"]), float(row["valuation_ratio"])))
    return out


def load_prices() -> dict[str, dict[str, float]]:
    """持仓在**没有带**的日子也要按市价盯市，故行情单独全量载入。"""
    out: dict[str, dict[str, float]] = {}
    for path in sorted(OHLCV_DIR.glob("*.csv")):
        if path.stem.startswith("INDEX_"):
            continue
        series = {}
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                close = _num(row.get("close"))
                if close and close > 0:
                    series[row["date"]] = close
        out[path.stem] = series
    return out


def load_actions() -> dict[str, dict[str, tuple[float, float]]]:
    """{代码: {除权日: (每股现金红利, 送转比)}}。同日多条相加/连乘。"""
    out: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    if not ACTIONS.exists():
        return out
    with ACTIONS.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = (row.get("ex_dividend_date") or "").strip()
            if not day:
                continue
            cash = _num(row.get("cash_per_share")) or 0.0
            ratio = _num(row.get("share_ratio")) or 0.0
            old_cash, old_ratio = out[row["security_code"]].get(day, (0.0, 0.0))
            out[row["security_code"]][day] = (old_cash + cash, (1 + old_ratio) * (1 + ratio) - 1)
    return out


def load_names() -> dict[str, str]:
    path = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r["security_name"] for r in csv.DictReader(handle)}


def load_tiers() -> dict[str, str]:
    """{代码: 档位}——买入线按档位分档时用（--use-mos）。"""
    path = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {r["security_code"]: r["quality_tier"] for r in csv.DictReader(handle)}


def load_benchmark() -> dict[str, float]:
    if not BENCHMARK.exists():
        return {}
    with BENCHMARK.open(newline="", encoding="utf-8") as handle:
        return {r["date"]: float(r["close"]) for r in csv.DictReader(handle) if _num(r.get("close"))}


def load_risk_free() -> list[tuple[str, float]]:
    if not RATES.exists():
        return []
    with RATES.open(newline="", encoding="utf-8") as handle:
        return sorted((r["observed_on"], float(r["risk_free_rate"])) for r in csv.DictReader(handle))


def new_low_flags(series: dict[str, float], lookback: int = 20) -> dict[str, bool]:
    """{日期: 当日收盘是否创 `lookback` 日新低}。「止跌走稳」判据的原料。"""
    days = sorted(series)
    values = [series[d] for d in days]
    out = {}
    for i, v in enumerate(values):
        window = values[max(0, i - lookback + 1): i + 1]
        out[days[i]] = v <= min(window) + 1e-12
    return out


def stabilized(flags: dict[str, bool], days: list[str], index: dict[str, int],
               day: str, quiet: int = 5) -> bool:
    """**止跌走稳**：最近 `quiet` 个交易日内**一次都没有创过 20 日新低**。

    用户 2026-08-08 原述「下跌后止跌走稳才买，例如五日内不破新低」。选这个判据而不是
    「站上某条均线」，是因为它**只要求下跌停住、不要求已经转涨**——估值组本就是左侧买法，
    要求转涨等于把它变成走势组。
    """
    i = index.get(day)
    if i is None or i < quiet:
        return False
    return not any(flags.get(days[j], False) for j in range(i - quiet + 1, i + 1))


def moving_averages(series: dict[str, float], windows=(20, 60)) -> dict[str, dict[int, float]]:
    """逐日均线。走势组的入场与止损都要用。"""
    days = sorted(series)
    values = [series[d] for d in days]
    out: dict[str, dict[int, float]] = {}
    for window in windows:
        total = 0.0
        for index, value in enumerate(values):
            total += value
            if index >= window:
                total -= values[index - window]
            if index >= window - 1:
                out.setdefault(days[index], {})[window] = total / window
    return out


# ------------------------------------------------------------------ 组合
@dataclass
class Lot:
    """一个**建仓→清仓周期**。分批买入合并进同一周期，直到清空才结算。"""
    code: str
    entry_date: str
    entry_ratio: float          # 建仓当日 P/V
    entry_value: float          # 建仓当日内在价值
    entry_band_low: float
    entry_band_high: float
    entry_upside: float         # 建仓当日「空间」= V/P − 1
    shares: float = 0.0
    invested: float = 0.0       # 累计买入金额
    proceeds: float = 0.0       # 累计卖出金额 + 累计现金分红
    dividends: float = 0.0
    buys: int = 0
    sells: int = 0
    peak_price: float = 0.0     # 持有期内的价格峰值（**周期内最大回撤按价格算**）
    max_drawdown: float = 0.0   # 1 − 价格/峰值 的最大值
    peak_money: float = 0.0     # (持仓市值+已回收)/累计投入 的峰值
    max_money_drawdown: float = 0.0
    entry_stop: float = 0.0     # 建仓日止损价（见 entry_stop_price）
    entry_stop_ma: int = 0      # 实际采用的均线周期——买在 MA60 下方时会退回 20
    peak_intrinsic: float = 0.0 # 持有期内内在价值的峰值——**基本面退出**按它的回撤触发
    exit_date: str = ""
    exit_reason: str = ""


@dataclass
class Portfolio:
    cash: float
    lots: dict[str, Lot] = field(default_factory=dict)
    closed: list[Lot] = field(default_factory=list)

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for code, lot in self.lots.items():
            price = prices.get(code)
            if price:
                total += lot.shares * price
        return total


def apply_corporate_actions(portfolio: Portfolio, day: str,
                            actions: dict[str, dict[str, tuple[float, float]]]) -> float:
    """除权日调股数、派息入现金。**不做这步整个回测就是错的**（穿越 10 转 10 会凭空亏一半）。"""
    credited = 0.0
    for code, lot in portfolio.lots.items():
        event = actions.get(code, {}).get(day)
        if not event:
            continue
        cash_per_share, ratio = event
        cash = lot.shares * cash_per_share
        portfolio.cash += cash
        lot.dividends += cash
        lot.proceeds += cash
        credited += cash
        lot.shares *= (1 + ratio)
    return credited


def entry_stop_price(ma: dict[int, float], close: float, stop_ma: int) -> tuple[float, int]:
    """建仓日的止损价，返回 (价格, 实际采用的均线周期)。

    用户 2026-08-08 规则：**优先用 MA60；但若建仓时股价已在 MA60 下方，则退回 MA20。**
    理由是买在 MA60 之下时，拿 MA60 当止损等于**建仓即触发**——止损价高于成本价，
    这条止损不是保护而是立刻把仓位打掉。退回 MA20 才可能落在成本价下方。
    """
    if stop_ma == 20:
        return ma.get(20, 0.0), 20
    ma60 = ma.get(60, 0.0)
    if ma60 and close >= ma60:
        return ma60, 60
    return ma.get(20, 0.0), 20


def close_lot(portfolio: Portfolio, code: str, day: str, price: float, reason: str) -> None:
    lot = portfolio.lots.pop(code)
    portfolio.cash += lot.shares * price
    lot.proceeds += lot.shares * price
    lot.shares = 0.0
    lot.exit_date, lot.exit_reason = day, reason
    lot.sells += 1
    portfolio.closed.append(lot)


# ------------------------------------------------------------------ 回测
def run(strategy: str, x: float, states, prices, actions, mas, since: str, until: str,
        capital: float, width: float = 0.10, tiers: dict[str, str] | None = None,
        use_mos: bool = False, price_stop: bool = False, value_stop: float = 0.0,
        stop_ma: int = 20, trend_stop: bool = True, entry_filter: str = "none",
        lump_sum: float = 0.0, swap: bool = False, swap_margin: float = 0.10,
        max_positions: int = MAX_POSITIONS, lows=None, day_index=None) -> dict:
    """`width` 即带的半宽 w：买入线 `P/V ≤ 1−w`、减持线 `P/V ≥ 1+w`。

    `use_mos`：买入线改按档位的安全边际取 `1 − MOS_档`（L1 0.90／L2 0.80／L3 0.70）。
    **MOS 只管买、不管卖**——安全边际是「便宜到什么程度才敢下手」，卖出仍按带上沿。
    这是 §6.5.7.1.1「估值层给 r、决策层给 MOS」那条分工的落地；此前 MOS 只算进带文件的
    `max_buy_price` 列，回测一行都没引用（§15.2 第 2 条「成文未落地」，本轮补上）。

    `price_stop`：给估值组也装上走势组那套「跌破建仓日 MA20 即清仓」。
    `value_stop`：**基本面退出**——内在价值自持有期峰值回落超过该比例即清仓。
    它直接盯 V 而不盯价格，是对「业绩下滑→越跌越贵」那条链路的正面处理：
    实测现行规则下这条链路虽然存在（64 次减持里 10 次由 V 下修触发），但**太慢**
    ——徐工机械那一笔从建仓到被判贵走了 9 年半。
    """
    portfolio = Portfolio(cash=capital)
    days = sorted(d for d in states if since <= d <= until)
    last_price: dict[str, float] = {}   # 停牌日没有行情，须沿用最后成交价盯市
    equity_curve: list[tuple[str, float, float, int]] = []
    buy_count = sell_count = 0
    turnover = 0.0
    tiers = tiers or {}
    sell_line = 1.0 + width

    def buy_line(code: str) -> float:
        if use_mos:
            return 1.0 - MOS_BY_TIER.get(tiers.get(code, DEFAULT_TIER), width)
        return 1.0 - width

    for day in days:
        apply_corporate_actions(portfolio, day, actions)
        today = {code: (close, value, ratio) for code, close, value, ratio in states[day]}
        # 停牌股当日无价，**必须沿用最后成交价**——否则它会整只从净值里消失，
        # 复牌当天再凭空出现，资金曲线上是一对假的暴跌+暴涨。
        marks = {}
        for code in portfolio.lots:
            price = today[code][0] if code in today else prices.get(code, {}).get(day)
            if price:
                last_price[code] = price
            if code in last_price:
                marks[code] = last_price[code]
        equity = portfolio.equity(marks)
        if equity <= 0:
            break
        budget = equity * x

        # ---- 周期内回撤。**必须按价格算，不能按持仓市值算**：分批买入会推高市值、分批卖出
        # 会压低市值，两者都与价格无关。首版按市值算，结果三环集团 +8.5% 收益却报出
        # 「周期内最大回撤 99.2%」——那 99% 全是减仓造成的，不是股价跌的。
        # 另记一条**资金口径**回撤 (持仓市值+已回收)/累计投入，用来看这笔钱最差时浮亏多少。
        for code, lot in portfolio.lots.items():
            price = marks.get(code)
            if not price:
                continue
            lot.peak_price = max(lot.peak_price, price)
            if lot.peak_price > 0:
                lot.max_drawdown = max(lot.max_drawdown, 1 - price / lot.peak_price)
            current_value = today.get(code, (None, None, None))[1]
            if current_value:
                lot.peak_intrinsic = max(lot.peak_intrinsic, current_value)
            if lot.invested > 0:
                money = (lot.shares * price + lot.proceeds) / lot.invested
                lot.peak_money = max(lot.peak_money, money)
                lot.max_money_drawdown = max(lot.max_money_drawdown, 1 - money / lot.peak_money)

        # ---- 卖出（先卖后买：卖出释放的现金当日即可用，与「有资金就买」一致）
        for code in list(portfolio.lots):
            lot, price = portfolio.lots[code], marks.get(code)
            if not price:
                continue
            ratio = today.get(code, (None, None, None))[2]
            if ((strategy == "trend" and trend_stop) or price_stop) and lot.entry_stop and price < lot.entry_stop:
                turnover += lot.shares * price     # 必须在 close_lot 之前取——它会把 shares 清零
                close_lot(portfolio, code, day, price, f"跌破建仓日MA{lot.entry_stop_ma}止损")
                sell_count += 1
                continue
            # 基本面退出：内在价值自峰值回落超阈值即清仓。**盯 V 不盯价**，故一只票可以
            # 在股价没怎么跌的时候就被卖掉——那正是「业绩塌了但市场还没反应」的情形。
            if value_stop and lot.peak_intrinsic > 0:
                current_value = today.get(code, (None, None, None))[1]
                if current_value and current_value <= lot.peak_intrinsic * (1 - value_stop):
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, f"内在价值自峰值回落≥{value_stop:.0%}")
                    sell_count += 1
                    continue
            if ratio is not None and ratio >= sell_line:
                shares = min(lot.shares, budget / price)
                if shares <= 0:
                    continue
                if shares >= lot.shares * 0.999:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, f"P/V≥{sell_line:.2f}清空")
                else:
                    lot.shares -= shares
                    portfolio.cash += shares * price
                    lot.proceeds += shares * price
                    lot.sells += 1
                    turnover += shares * price
                sell_count += 1

        # ---- 买入：合格集为空则持币（用户 2026-08-08 裁定），**不硬凑前十**
        eligible = sorted((r for r in states[day] if r[3] <= buy_line(r[0])), key=lambda r: r[3])
        if strategy == "trend":
            eligible = [r for r in eligible
                        if (ma := mas.get(r[0], {}).get(day)) and 20 in ma and 60 in ma
                        and r[1] > ma[20] > ma[60]]
        if entry_filter == "stabilized" and lows is not None:
            eligible = [r for r in eligible
                        if stabilized(lows.get(r[0], {}), day_index[0].get(r[0], []),
                                      day_index[1].get(r[0], {}), day)]
        # 换仓：想买却买不下（没钱或槽位满）时，把**空间最小**的持仓换成**空间更大**的候选。
        # `swap_margin` 是防抖阈值——两者 P/V 差不到这个数就不换，否则每天的微小排名波动
        # 都会触发一次双边交易。
        if swap and eligible:
            for code, close, value, ratio in eligible[:max_positions]:
                if code in portfolio.lots:
                    continue
                blocked = portfolio.cash < (lump_sum or budget) or len(portfolio.lots) >= max_positions
                if not blocked:
                    break
                held = [(today[c][2], c) for c in portfolio.lots if c in today]
                if not held:
                    break
                worst_ratio, worst = max(held)
                if worst_ratio - ratio < swap_margin:
                    break
                price = marks.get(worst)
                if not price:
                    break
                turnover += portfolio.lots[worst].shares * price
                close_lot(portfolio, worst, day, price, f"换仓：让位给空间更大的{code}")
                sell_count += 1
        for code, close, value, ratio in eligible[:max_positions]:
            if portfolio.cash <= 0:
                break
            if (strategy == "trend" or lump_sum) and code in portfolio.lots:
                continue                      # 一笔建仓：不加仓
            if lump_sum:
                amount = min(equity * lump_sum, portfolio.cash)
            else:
                amount = min(budget if strategy == "valuation" else equity / max_positions,
                             portfolio.cash)
            if amount <= 0 or code not in portfolio.lots and len(portfolio.lots) >= max_positions:
                continue
            shares = amount / close
            lot = portfolio.lots.get(code)
            if lot is None:
                ma = mas.get(code, {}).get(day, {})
                lot = Lot(code=code, entry_date=day, entry_ratio=ratio, entry_value=value,
                          entry_band_low=(1 - width) * value, entry_band_high=(1 + width) * value,
                          entry_upside=value / close - 1, peak_intrinsic=value)
                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(ma, close, stop_ma)
                portfolio.lots[code] = lot
            lot.shares += shares
            lot.invested += amount
            lot.buys += 1
            portfolio.cash -= amount
            buy_count += 1
            turnover += amount

        # **收盘净值必须对当日新建的仓位也取到价**：`marks` 是开盘前按当时持仓建的，
        # 当天新买的票不在里面，`equity()` 会把它们记作 0——现金花掉了、股票却不算数，
        # 次日再凭空出现。首版即此错，实测造成单日 −39.2% 紧接 +41.6% 的假波动
        # （组合年化波动被抬到 70%+，54 个交易日单日振幅 >20%）。
        for code in portfolio.lots:
            if code not in marks:
                price = today[code][0] if code in today else prices.get(code, {}).get(day)
                if price:
                    last_price[code] = price
                if code in last_price:
                    marks[code] = last_price[code]
        equity_curve.append((day, portfolio.equity(marks), portfolio.cash, len(portfolio.lots)))

    # 收尾：按最后一日收盘价清算未平仓，使逐周期收益可比
    if days:
        last = days[-1]
        for code in list(portfolio.lots):
            price = prices.get(code, {}).get(last)
            if price:
                close_lot(portfolio, code, last, price, "回测截止清算")
    return {"equity": equity_curve, "closed": portfolio.closed,
            "buys": buy_count, "sells": sell_count, "turnover": turnover}


# ------------------------------------------------------------------ 指标
def period_returns(curve: list[tuple[str, float, float, int]], key) -> list[tuple[str, float]]:
    buckets: dict[str, tuple[float, float]] = {}
    for day, equity, _cash, _n in curve:
        label = key(day)
        first, _ = buckets.get(label, (equity, equity))
        buckets[label] = (first, equity)
    return [(k, last / first - 1) for k, (first, last) in sorted(buckets.items())]


def max_drawdown(curve) -> tuple[float, str, str]:
    peak, worst, start, end, peak_day = -1.0, 0.0, "", "", ""
    for day, equity, _c, _n in curve:
        if equity > peak:
            peak, peak_day = equity, day
        elif peak > 0:
            drop = 1 - equity / peak
            if drop > worst:
                worst, start, end = drop, peak_day, day
    return worst, start, end


def summarize(name: str, result: dict, capital: float, benchmark: dict[str, float],
              risk_free: list[tuple[str, float]]) -> dict:
    curve = result["equity"]
    if not curve:
        return {}
    final = curve[-1][1]
    years = len(curve) / TRADING_DAYS
    cagr = (final / capital) ** (1 / years) - 1 if years > 0 and final > 0 else float("nan")
    rets = [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve)) if curve[i - 1][1] > 0]
    vol = statistics.pstdev(rets) * math.sqrt(TRADING_DAYS) if len(rets) > 2 else float("nan")
    worst, dd_start, dd_end = max_drawdown(curve)
    rf = statistics.fmean([r for _, r in risk_free]) if risk_free else 0.0
    sharpe = (cagr - rf) / vol if vol and not math.isnan(vol) and vol > 0 else float("nan")
    exposure = statistics.fmean([1 - c / e for _d, e, c, _n in curve if e > 0])

    closed = result["closed"]
    wins = [l for l in closed if l.proceeds > l.invested]
    profits = [l.proceeds - l.invested for l in closed]
    holding = [_days_between(l.entry_date, l.exit_date) for l in closed if l.exit_date]

    bench = ""
    if benchmark:
        pair = [(d, benchmark[d]) for d, *_ in curve if d in benchmark]
        if len(pair) > 1:
            # 基准年化须用**基准自身覆盖到的天数**，不能套策略的 years（两者起点可能不同）
            bench_years = len(pair) / TRADING_DAYS
            bench_cagr = (pair[-1][1] / pair[0][1]) ** (1 / bench_years) - 1
            bench = f"{bench_cagr:.2%}（同期超额 {cagr - bench_cagr:+.2%}）"

    return {"策略": name, "期末资产": final, "总收益": final / capital - 1, "年化": cagr,
            "年化波动": vol, "最大回撤": worst, "回撤区间": f"{dd_start}~{dd_end}",
            "Calmar": cagr / worst if worst else float("nan"), "Sharpe": sharpe,
            "平均仓位": exposure, "周期数": len(closed),
            "胜率": len(wins) / len(closed) if closed else float("nan"),
            "盈亏比": (statistics.fmean([p for p in profits if p > 0]) /
                    abs(statistics.fmean([p for p in profits if p <= 0]))
                    if any(p > 0 for p in profits) and any(p <= 0 for p in profits) else float("nan")),
            "平均持有天数": statistics.fmean(holding) if holding else float("nan"),
            "买入笔数": result["buys"], "卖出笔数": result["sells"],
            "年均换手": (result["turnover"] / years / statistics.fmean([e for _d, e, _c, _n in curve])
                     if years else float("nan")),
            "基准年化": bench}


def _days_between(a: str, b: str) -> int:
    from datetime import date
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


TRADE_FIELDS = ["security_code", "security_name", "entry_date", "exit_date", "holding_days",
                "buys", "sells", "invested", "proceeds", "dividends", "return_pct",
                "max_drawdown_in_cycle", "max_money_drawdown", "entry_stop", "entry_stop_ma", "entry_pv_ratio", "entry_upside", "entry_intrinsic_value",
                "entry_band_low", "entry_band_high", "exit_reason"]


def write_trades(path: Path, lots, names: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for lot in sorted(lots, key=lambda l: l.entry_date):
            writer.writerow({
                "security_code": lot.code, "security_name": names.get(lot.code, ""),
                "entry_date": lot.entry_date, "exit_date": lot.exit_date,
                "holding_days": _days_between(lot.entry_date, lot.exit_date) if lot.exit_date else "",
                "buys": lot.buys, "sells": lot.sells,
                "invested": f"{lot.invested:.2f}", "proceeds": f"{lot.proceeds:.2f}",
                "dividends": f"{lot.dividends:.2f}",
                "return_pct": f"{lot.proceeds / lot.invested - 1:.6f}" if lot.invested else "",
                "max_drawdown_in_cycle": f"{lot.max_drawdown:.6f}",
                "max_money_drawdown": f"{lot.max_money_drawdown:.6f}",
                "entry_stop": f"{lot.entry_stop:.4f}", "entry_stop_ma": lot.entry_stop_ma or "",
                "entry_pv_ratio": f"{lot.entry_ratio:.4f}", "entry_upside": f"{lot.entry_upside:.4f}",
                "entry_intrinsic_value": f"{lot.entry_value:.4f}",
                "entry_band_low": f"{lot.entry_band_low:.4f}",
                "entry_band_high": f"{lot.entry_band_high:.4f}",
                "exit_reason": lot.exit_reason})


def write_equity(path: Path, curve) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "total_equity", "cash", "positions", "cash_ratio"])
        for day, equity, cash, count in curve:
            writer.writerow([day, f"{equity:.2f}", f"{cash:.2f}", count,
                             f"{cash / equity:.4f}" if equity else ""])


def write_periods(path: Path, curve) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["period_type", "period", "return_pct"])
        for label, value in period_returns(curve, lambda d: d[:4]):
            writer.writerow(["annual", label, f"{value:.6f}"])
        for label, value in period_returns(curve, lambda d: d[:7]):
            writer.writerow(["monthly", label, f"{value:.6f}"])


def main() -> int:
    parser = argparse.ArgumentParser(description="OI-034 估值组/走势组回测")
    parser.add_argument("--strategy", choices=("valuation", "trend", "both"), default="both")
    parser.add_argument("--x", type=float, nargs="+", default=[1.0, 0.5, 0.1],
                        help="每次调仓占总资产的百分比，可给多个做参数扫描")
    parser.add_argument("--since", default="2000-01-01")
    parser.add_argument("--until", default="2026-08-07")
    parser.add_argument("--capital", type=float, default=INITIAL_CAPITAL)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--width", type=float, nargs="+", default=[0.10],
                        help="带的半宽 w：买入线 1−w、减持线 1+w。可给多个做敏感度")
    parser.add_argument("--use-mos", action="store_true",
                        help="买入线改按档位安全边际 1−MOS（L1 0.90/L2 0.80/L3 0.70）")
    parser.add_argument("--price-stop", action="store_true", help="估值组也用建仓日均线止损")
    parser.add_argument("--stop-ma", type=int, choices=(20, 60), default=20,
                        help="止损均线周期；取 60 时，若建仓价已在 MA60 下方则自动退回 MA20")
    parser.add_argument("--value-stop", type=float, default=0.0,
                        help="基本面退出：内在价值自峰值回落超该比例即清仓，如 0.25")
    parser.add_argument("--no-trend-stop", dest="trend_stop", action="store_false",
                        help="走势组取消建仓日均线止损")
    parser.add_argument("--entry-filter", choices=("none", "stabilized"), default="none",
                        help="stabilized=止跌走稳（近 5 个交易日未创 20 日新低）才允许买入")
    parser.add_argument("--lump-sum", type=float, default=0.0,
                        help="一笔建仓，占总资产的百分比（如 5）；给了就不再定投加仓")
    parser.add_argument("--swap", action="store_true",
                        help="买不下时卖出空间最小的持仓，换空间更大的候选")
    parser.add_argument("--swap-margin", type=float, default=0.10, help="换仓的 P/V 最小改善，防抖")
    parser.add_argument("--max-positions", type=int, default=MAX_POSITIONS)
    parser.add_argument("--label-suffix", default="")
    args = parser.parse_args()

    print(f"载入…（逐日估值状态、行情、除权除息、均线）")
    states, prices, actions = load_states(), load_prices(), load_actions()
    names, benchmark, risk_free = load_names(), load_benchmark(), load_risk_free()
    mas = {code: moving_averages(series) for code, series in prices.items()}
    lows = {code: new_low_flags(series) for code, series in prices.items()}
    day_lists = {code: sorted(series) for code, series in prices.items()}
    day_pos = {code: {d: i for i, d in enumerate(ds)} for code, ds in day_lists.items()}
    covered = sorted(states)
    print(f"  逐日状态 {sum(len(v) for v in states.values()):,} 行｜"
          f"{covered[0]} ~ {covered[-1]}｜行情 {len(prices)} 只｜"
          f"基准 {'沪深300 ' + str(len(benchmark)) + ' 日' if benchmark else '**缺**'}")
    if args.since < covered[0]:
        print(f"  ⚠ 请求起点 {args.since} 早于估值状态起点 **{covered[0]}**，"
              f"实际从后者起跑（历史带需先有逐季财务与五年年报 ROE，见 §12.4.3）")

    tiers = load_tiers()
    strategies = ["valuation", "trend"] if args.strategy == "both" else [args.strategy]
    rows = []
    for strategy in strategies:
      for width in args.width:
        for x in args.x:
            label = (f"{strategy}_x{x:g}_w{width:g}"
                     + ("_mos" if args.use_mos else "")
                     + (f"_ma{args.stop_ma}" if args.price_stop else "")
                     + (f"_vstop{args.value_stop:g}" if args.value_stop else "")
                     + ("_stab" if args.entry_filter == "stabilized" else "")
                     + (f"_lump{args.lump_sum:g}" if args.lump_sum else "")
                     + ("_swap" if args.swap else "")
                     + ("" if args.trend_stop else "_nostop")
                     + args.label_suffix)
            result = run(strategy, x / 100.0, states, prices, actions, mas,
                         args.since, args.until, args.capital, width=width, tiers=tiers,
                         use_mos=args.use_mos, price_stop=args.price_stop,
                         value_stop=args.value_stop, stop_ma=args.stop_ma,
                         trend_stop=args.trend_stop, entry_filter=args.entry_filter,
                         lump_sum=args.lump_sum / 100.0, swap=args.swap,
                         swap_margin=args.swap_margin, max_positions=args.max_positions,
                         lows=lows, day_index=(day_lists, day_pos))
            if not result["equity"]:
                print(f"  {label}: 无交易日")
                continue
            write_trades(args.out_dir / f"{label}_trades.csv", result["closed"], names)
            write_equity(args.out_dir / f"{label}_equity.csv", result["equity"])
            write_periods(args.out_dir / f"{label}_periods.csv", result["equity"])
            summary = summarize(label, result, args.capital, benchmark, risk_free)
            rows.append(summary)
            print(f"  {label}: 期末 {summary['期末资产']/1e4:,.1f} 万｜年化 {summary['年化']:.2%}"
                  f"｜最大回撤 {summary['最大回撤']:.1%}｜周期 {summary['周期数']}")

    if rows:
        with (args.out_dir / f"summary{args.label_suffix or ''}.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        try:
            where = args.out_dir.relative_to(ROOT)
        except ValueError:
            where = args.out_dir
        print(f"\n落点 {where}/：逐周期 *_trades.csv、"
              f"逐日 *_equity.csv、年月收益 *_periods.csv、汇总 summary.csv")
    print("\n⚠ **两处结构性偏误**：①标的是今日 261 只池内股，池由 2026 年的分层选出，"
          "2000 年时仅 34 只在市——起点越早，幸存者偏差与选样前视越重；②不计交易成本，"
          "对高换手（大 x）一侧更有利。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
