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
import collections
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
def load_states(path: Path | None = None,
                codes: set[str] | None = None) -> dict[str, list[tuple[str, float, float, float]]]:
    """{日期: [(代码, 收盘, 内在价值, P/V), …]}——已按送转折算过的口径。

    `codes` 限定载入范围。全市场建带后逐日状态上千万行，全量驻留内存要好几 GB；
    给了时点股票库就只需要它的历年并集，其余行读了也用不上。
    """
    out: dict[str, list[tuple[str, float, float, float]]] = defaultdict(list)
    with (path or DAILY_STATES).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if codes is not None and row["security_code"] not in codes:
                continue
            out[row["date"]].append((row["security_code"], float(row["close"]),
                                     float(row["intrinsic_value"]), float(row["valuation_ratio"])))
    return out


def load_prices(codes: set[str] | None = None) -> dict[str, dict[str, float]]:
    """持仓在**没有带**的日子也要按市价盯市，故行情单独载入。

    `codes` 限定范围。全市场 5,000+ 只行情读成 dict 要 3~4 GB——**在 8 GB 机器上，
    与逐日状态叠加会把系统拖死**（2026-08-08 实测：4 个回测并行导致两次黑屏）。
    只有出现在逐日状态里的代码才可能被买或被盯市，其余读了也用不上。
    """
    out: dict[str, dict[str, float]] = {}
    for path in sorted(OHLCV_DIR.glob("*.csv")):
        if path.stem.startswith("INDEX_") or (codes is not None and path.stem not in codes):
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


def load_universe(path: Path) -> list[tuple[str, set[str]]]:
    """时点股票库：[(生效日, {代码})]，按生效日升序。

    每档名单从 `effective_from` 起生效到下一档生效前一日。**生效日不可提前**——
    `Y` 年的年报要到 `Y+1` 年 4 月底才披露完，见 `build_point_in_time_universe.py`。
    """
    by_date: dict[str, set[str]] = defaultdict(set)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            by_date[row["effective_from"]].add(row["security_code"])
    return sorted(by_date.items())


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


def daily_returns(prices: dict[str, dict[str, float]],
                  actions: dict[str, dict[str, tuple[float, float]]]) -> dict[str, dict[str, float]]:
    """逐票日收益率。**必须按送转折算**，否则除权日会被当成一次 −50% 的暴跌算进相关性。"""
    out: dict[str, dict[str, float]] = {}
    for code, series in prices.items():
        days = sorted(series)
        ret = {}
        for prev, cur in zip(days, days[1:]):
            base = series[prev]
            cash, ratio = actions.get(code, {}).get(cur, (0.0, 0.0))
            if base > 0:
                ret[cur] = (series[cur] * (1 + ratio) + cash) / base - 1
        out[code] = ret
    return out


class Correlations:
    """按月缓存的两两相关性。**按需计算**——每天只用得到「候选前几十只 + 现有持仓」，
    全市场 261×261 全算是 3.4 万对 × 170 个月，纯 Python 跑不动也没必要。
    """

    def __init__(self, returns, window: int = 252, min_overlap: int = 120):
        self.returns = returns
        self.window = window
        self.min_overlap = min_overlap
        self._cache: dict[tuple, float | None] = {}
        self._std: dict[tuple, tuple] = {}

    def _series(self, code: str, month: str):
        key = (code, month)
        if key not in self._std:
            days = [d for d in sorted(self.returns.get(code, {})) if d[:7] < month]
            days = days[-self.window:]
            values = [self.returns[code][d] for d in days]
            if len(values) < self.min_overlap:
                self._std[key] = ({}, 0.0)
            else:
                self._std[key] = ({d: v for d, v in zip(days, values)}, 0.0)
        return self._std[key][0]

    def get(self, a: str, b: str, day: str) -> float | None:
        """`day` 当月之前满一年的日收益率相关系数；重叠不足返回 None（**当作未知、不当作 0**）。"""
        if a == b:
            return 1.0
        month = day[:7]
        key = (month, a, b) if a < b else (month, b, a)
        if key in self._cache:
            return self._cache[key]
        sa, sb = self._series(a, month), self._series(b, month)
        common = sa.keys() & sb.keys()
        if len(common) < self.min_overlap:
            self._cache[key] = None
            return None
        xs = [sa[d] for d in common]
        ys = [sb[d] for d in common]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        value = num / (dx * dy) if dx > 0 and dy > 0 else None
        self._cache[key] = value
        return value


# 档位排序偏置。用户 2026-08-08 提出「L1 空间 +20/+10 再跟 L2 排序」。
TIER_BONUS = {"L1": 0.20, "L2": 0.10, "L3": 0.0}
TIER_QUOTA = {"L1": 4, "L2": 5, "L3": 1}


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


def moving_averages(series: dict[str, float], windows=(5, 10, 20, 60, 120, 240)) -> dict[str, dict[int, float]]:
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
        max_positions: int = MAX_POSITIONS, lows=None, day_index=None,
        max_corr: float = 0.0, corr=None, tier_mode: str = "none",
        scan_depth: int = 40, min_upside: dict[str, float] | None = None,
        position_cap: float = 0.0, only_tiers: set[str] | None = None,
        universe: list[tuple[str, set[str]]] | None = None,
        trend_tranche: bool = False, trend_ma: tuple[int, ...] = (20, 60),
        sell_line_override: float | None = None, trend_exit_ma: int = 0,
        rank_by_upside: bool = True, entry_mode: str = "trend", dev_ma: int = 60,
        dev_buy_max: float = 1.10, dev_sell_min: float = 0.0,
        hold_strong: str = "off", hold_strong_ma: tuple[int, ...] = (),
        rank_mode: str = "pv", quantile_window: int = 0,
        quantile_min_obs: int = 250) -> dict:
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
    # 减持线可独立于带宽设定：`--sell-line 1.30` 表示涨到 P/V=1.30 才开始减持，
    # 用来检验「让利润跑得更远」是否有效（实测 P/V≥1.10 清空的 17 笔中位 +28.6%、胜率 88%）。
    sell_line = sell_line_override if sell_line_override else 1.0 + width
    # 时点股票库：`members` 随日期切换。第一档生效前**一只都不可买**——那段时间还没有
    # 任何「当时可得」的名单，凭空放行等于用未来的股票库交易。
    uni_idx, members = 0, (set() if universe else None)
    # 相对便宜度排序：把当日 P/V 换算成「相对该股自身历史」的读数再排序。
    # 用户 2026-08-09：单一 P/V 升序使可选集退化为深度价值股（价值股 P/V 常年 0.3~0.6，
    # 成长股修正估值后也只到 0.8 上下，永远排在后面——实测中际旭创 2025-05 合格但列第 27）。
    #
    # 两种口径：
    #   `quantile` 百分位——**已实测在底部饱和**（§12.9.26：2025-05-09 合格集前十的分位
    #              全部是 0.00，中际旭创并列第 17），端点处退化为无信息并列。
    #   `ratio`    当前 P/V ÷ 历史中位 P/V——**连续量，跌破历史最低后仍可继续减小**，
    #              故在端点不饱和。中际旭创 0.88/历史中位 vs 招行 0.30/历史中位，可公平比较。
    #
    # **严格无前视**：历史只含当日之前已观测到的 P/V，逐日插入；窗口版同步淘汰最老一条，
    # 使排序表恰好等于窗口内容。观测不足 `quantile_min_obs` 时退回原始 P/V，不猜。
    from bisect import bisect_left, insort
    from collections import deque as _deque
    pv_order: dict[str, object] = defaultdict(_deque)   # 插入序，用于淘汰
    pv_sorted: dict[str, list[float]] = defaultdict(list)

    def push_pv(code: str, ratio: float) -> None:
        order, arr = pv_order[code], pv_sorted[code]
        order.append(ratio)
        insort(arr, ratio)
        if quantile_window and len(order) > quantile_window:
            old = order.popleft()
            del arr[bisect_left(arr, old)]

    def score_of(code: str, ratio: float) -> float:
        arr = pv_sorted[code]
        if rank_mode == "pv" or len(arr) < quantile_min_obs:
            return ratio
        if rank_mode == "quantile":
            return bisect_left(arr, ratio) / len(arr)
        n = len(arr)
        median = arr[n // 2] if n % 2 else (arr[n // 2 - 1] + arr[n // 2]) / 2
        return ratio / median if median > 0 else ratio

    def buy_line(code: str) -> float:
        if use_mos:
            return 1.0 - MOS_BY_TIER.get(tiers.get(code, DEFAULT_TIER), width)
        return 1.0 - width

    for day in days:
        apply_corporate_actions(portfolio, day, actions)
        if universe:
            while uni_idx < len(universe) and universe[uni_idx][0] <= day:
                members = universe[uni_idx][1]
                uni_idx += 1
        today = {code: (close, value, ratio) for code, close, value, ratio in states[day]}
        scores = {code: score_of(code, r[2]) for code, r in today.items()} if rank_mode != "pv" else {}
        if rank_mode != "pv":
            for code, r in today.items():
                push_pv(code, r[2])
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
            # 移出股票库 → **逐步清仓**（用户 2026-08-08：「对于被移除股票库的公司，逐步清仓」）。
            # 按与减持同一速度卖，不一次性砸出——一年一次的换库若全额出清，会在每年 5 月
            # 制造一次集中抛售，测出来的是流动性冲击而不是规则优劣。
            if members is not None and code not in members:
                shares = min(lot.shares, budget / price)
                if shares > 0:
                    if shares >= lot.shares * 0.999:
                        turnover += lot.shares * price
                        close_lot(portfolio, code, day, price, "移出股票库·逐步清仓")
                    else:
                        lot.shares -= shares
                        portfolio.cash += shares * price
                        lot.proceeds += shares * price
                        lot.sells += 1
                        turnover += shares * price
                    sell_count += 1
                continue
            # 走势退出：**跟随均线**而非建仓日固定价。用户 2026-08-09：「把跌破120日均线作为
            # 减仓阈值」。与 `--price-stop` 的区别是后者盯建仓当日那条静态止损价，此处盯当日均线。
            # 偏离度卖出：涨到中期均线的 `dev_sell_min` 倍以上即清仓。用户 2026-08-09：
            # 「涨的比中期均线高很多就卖出」。与 P/V 减持线的区别是它盯**价格相对自身均线的位置**，
            # 与内在价值无关，故在估值带失真时仍可用。
            if dev_sell_min:
                ma_now = mas.get(code, {}).get(day, {})
                base = ma_now.get(dev_ma)
                if base and price >= base * dev_sell_min:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, f"偏离MA{dev_ma}达{dev_sell_min:.0%}清仓")
                    sell_count += 1
                    continue
            if trend_exit_ma:
                ma_now = mas.get(code, {}).get(day, {})
                if trend_exit_ma in ma_now and price < ma_now[trend_exit_ma]:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, f"跌破MA{trend_exit_ma}清仓")
                    sell_count += 1
                    continue
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
            # 强势多头豁免减持：空间缩小不卖，等趋势自己走坏或财报更新带改变格局。
            if (hold_strong in ("sell", "both") and strong_bull(code, day)):
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
        pool = states[day] if members is None else [r for r in states[day] if r[0] in members]
        # `rank_by_upside=False`：空间只作**阈值**不作排序，合格集内按代码排序（中性顺序），
        # 即「只要空间够 + 走势好就买」，不再优先买最便宜的。用户 2026-08-09 提出的对照口径。
        def _key(r):
            if not rank_by_upside:
                return r[0]
            return scores.get(r[0], r[3]) if rank_mode != "pv" else r[3]
        eligible = sorted((r for r in pool if r[3] <= buy_line(r[0])), key=_key)
        # 分档最低空间门槛（用户 2026-08-08：L1 >30%、L2 >40%；**L3 未指定，本脚本按 L2 取 40%**
        # ——L3 风险更高，门槛不该比 L2 松）。空间 = V/P − 1 = 1/(P/V) − 1。
        if min_upside:
            eligible = [r for r in eligible
                        if (1.0 / r[3] - 1.0) >= min_upside.get(tiers.get(r[0], DEFAULT_TIER), 0.0)]
        if only_tiers:
            eligible = [r for r in eligible if tiers.get(r[0], DEFAULT_TIER) in only_tiers]
        # 入场模式：trend=收盘>MA20>MA60（方向）；deviation=收盘 ≤ MA60×dev_buy_max（位置）；
        # both=两者同时满足。**方向与位置是两件事**——方向判断趋势是否成立，位置判断是否追高。
        if strategy == "trend" and entry_mode in ("deviation", "both"):
            kept = []
            for r in eligible:
                base = mas.get(r[0], {}).get(day, {}).get(dev_ma)
                if base and r[1] <= base * dev_buy_max:
                    kept.append(r)
            eligible = kept
        if strategy == "trend" and entry_mode in ("trend", "both"):
            eligible = [r for r in eligible
                        if (ma := mas.get(r[0], {}).get(day)) and all(w in ma for w in trend_ma)
                        and r[1] > ma[trend_ma[0]]
                        and (len(trend_ma) < 2 or ma[trend_ma[0]] > ma[trend_ma[1]])]
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
                held = [(scores.get(c, today[c][2]) if rank_mode != "pv" else today[c][2], c)
                        for c in portfolio.lots if c in today
                        and not (hold_strong in ("swap", "both") and strong_bull(c, day))]
                if not held:
                    break
                worst_ratio, worst = max(held)
                cand_score = scores.get(code, ratio) if rank_mode != "pv" else ratio
                if worst_ratio - cand_score < swap_margin:
                    break
                price = marks.get(worst)
                if not price:
                    break
                turnover += portfolio.lots[worst].shares * price
                close_lot(portfolio, worst, day, price, f"换仓：让位给空间更大的{code}")
                sell_count += 1
        # ---- 档位排序偏置（用户 2026-08-08）
        if tier_mode == "bonus":
            eligible.sort(key=lambda r: -(1.0 / r[3] + TIER_BONUS.get(tiers.get(r[0], DEFAULT_TIER), 0.0)))
        elif tier_mode == "quota":
            # 各档位各自排序，再按配额取——避免某一档因整体估值水平不同而被系统性挤出
            picked, used = [], collections.Counter()
            for r in eligible:
                t = tiers.get(r[0], DEFAULT_TIER)
                if used[t] < TIER_QUOTA.get(t, 0):
                    picked.append(r)
                    used[t] += 1
            picked += [r for r in eligible if r not in picked]
            eligible = picked

        # ---- 相关性过滤：**贪心**地沿排序往下走，与已选/已持仓相关性超阈值的跳过，
        # 顺位补下一名（用户 2026-08-08：「第一和第五相关性很强则跳过第五，考虑第 21 名」）。
        if max_corr and corr is not None:
            chosen, anchors = [], list(portfolio.lots)
            for r in eligible[:scan_depth]:
                if len(chosen) >= max_positions:
                    break
                if r[0] in portfolio.lots:
                    chosen.append(r)          # 已持仓的继续加仓，不受相关性约束
                    continue
                c = [corr.get(r[0], other, day) for other in anchors + [x[0] for x in chosen]]
                if any(v is not None and v > max_corr for v in c):
                    continue
                chosen.append(r)
            eligible = chosen

        for code, close, value, ratio in eligible[:max_positions]:
            if portfolio.cash <= 0:
                break
            # 走势组默认一笔建仓（总资产 ÷ 持仓上限）且不加仓；`trend_tranche` 打开后改为
            # **与估值组同一套定投**——只要当日仍满足「P/V 合格 且 收盘>MA20>MA60」就继续买入
            # 总资产 × x%。用户 2026-08-09：「走势满足要求的情况下分批进行建仓」。
            tranche = trend_tranche and strategy == "trend"
            if ((strategy == "trend" and not tranche) or lump_sum) and code in portfolio.lots:
                continue                      # 一笔建仓：不加仓
            if lump_sum:
                amount = min(equity * lump_sum, portfolio.cash)
            else:
                amount = min(budget if (strategy == "valuation" or tranche)
                             else equity / max_positions, portfolio.cash)
            if amount <= 0 or code not in portfolio.lots and len(portfolio.lots) >= max_positions:
                continue
            # 单票上限：**只挡加仓、不强制减持**——已有仓位因上涨超限是「买入上限」管不着的，
            # 强行削回去等于给策略偷加了一条止盈规则。
            if position_cap:
                held_value = portfolio.lots[code].shares * close if code in portfolio.lots else 0.0
                room = equity * position_cap - held_value
                if room <= 0:
                    continue
                amount = min(amount, room)
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


def rolling_calmar(curve, years: int = 3, step: int = 20) -> list[tuple[str, float, float, float]]:
    """滚动 `years` 年窗口的 (窗口末日, 窗口年化, 窗口最大回撤, 窗口 Calmar)。

    **与全期 Calmar 的区别要说清**：`summarize` 里的 `Calmar = 全期CAGR / 全期最大回撤`，
    它只有**一个**观测值，且分母是整段历史里最深的那一次——起点稍微一动就可能换成另一次
    崩盘，数值随之跳变（§12.9.2 已实测过这种路径敏感）。滚动口径给出**一串**观测值，
    可以看中位数与分布，比单点稳得多。
    """
    window = years * TRADING_DAYS
    out = []
    for end in range(window, len(curve), step):
        seg = curve[end - window:end]
        first, last = seg[0][1], seg[-1][1]
        if first <= 0 or last <= 0:
            continue
        cagr = (last / first) ** (1 / years) - 1
        peak, worst = -1.0, 0.0
        for _d, equity, _c, _n in seg:
            peak = max(peak, equity)
            if peak > 0:
                worst = max(worst, 1 - equity / peak)
        out.append((seg[-1][0], cagr, worst, cagr / worst if worst > 0 else float("nan")))
    return out


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

    roll = rolling_calmar(curve)
    roll_c = sorted(r[3] for r in roll if r[3] == r[3])
    roll_d = sorted(r[2] for r in roll)
    roll_g = sorted(r[1] for r in roll)
    return {"策略": name, "期末资产": final,
            "滚动3年Calmar中位": statistics.median(roll_c) if roll_c else float("nan"),
            "滚动3年Calmar_P10": roll_c[len(roll_c)//10] if roll_c else float("nan"),
            "滚动3年Calmar_P90": roll_c[-max(1,len(roll_c)//10)] if roll_c else float("nan"),
            "滚动3年回撤中位": statistics.median(roll_d) if roll_d else float("nan"),
            "滚动3年年化中位": statistics.median(roll_g) if roll_g else float("nan"),
            "滚动3年为负的窗口占比": (sum(1 for g in roll_g if g < 0)/len(roll_g)) if roll_g else float("nan"),
            "滚动窗口数": len(roll), "总收益": final / capital - 1, "年化": cagr,
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
    parser.add_argument("--max-corr", type=float, default=0.0,
                        help="相关性上限，如 0.7；与已选/已持仓相关性超过它的候选跳过、顺位补下一名")
    parser.add_argument("--corr-window", type=int, default=252, help="相关性回看交易日数")
    parser.add_argument("--scan-depth", type=int, default=40, help="相关性过滤时最多往下扫多少名")
    parser.add_argument("--tier-mode", choices=("none", "bonus", "quota"), default="none",
                        help="bonus=L1空间+20pp/L2+10pp 后再排序；quota=各档位分别排序并给买入额度")
    parser.add_argument("--min-upside", nargs=3, type=float, metavar=("L1", "L2", "L3"),
                        default=None, help="分档最低空间门槛，如 0.30 0.40 0.40")
    parser.add_argument("--position-cap", type=float, default=0.0,
                        help="单票买入上限占总资产比例，如 0.10；只挡加仓不强制减持")
    parser.add_argument("--only-tiers", default="", help="只买这些档位，逗号分隔，如 L1")
    parser.add_argument("--daily-states", type=Path, help="逐日估值状态文件，缺省用 261 池版本")
    parser.add_argument("--universe-file", type=Path,
                        help="时点股票库（build_point_in_time_universe.py 的产出）。"
                             "给了它就只在当期成员里选股，移出的持仓逐步清仓")
    parser.add_argument("--rank-mode", choices=("pv", "quantile", "ratio"), default="pv",
                        help="pv=原始 P/V 升序；quantile=历史分位（已实测底部饱和）；ratio=当前 P/V÷历史中位（连续量，端点不饱和）")
    parser.add_argument("--quantile-window", type=int, default=0,
                        help="分位数回看交易日数，0=自上市以来全历史")
    parser.add_argument("--quantile-min-obs", type=int, default=250,
                        help="历史观测少于该数时退回原始 P/V 排序，不猜")
    parser.add_argument("--hold-strong", choices=("off", "swap", "sell", "both"), default="off",
                        help="强势多头排列的持仓豁免：swap=不被换出／sell=不减持／both=两者")
    parser.add_argument("--hold-strong-ma", nargs="+", type=int, default=[20, 60, 120, 240],
                        help="多头排列所用均线，需严格递减，如 `20 60 120 240`")
    parser.add_argument("--entry-mode", choices=("trend", "deviation", "both"), default="trend",
                        help="trend=收盘>MA20>MA60；deviation=收盘≤中期均线×上限；both=两者同时")
    parser.add_argument("--dev-ma", type=int, default=60, help="偏离度所用的中期均线")
    parser.add_argument("--dev-buy-max", type=float, default=1.10,
                        help="买入上限：收盘 ≤ 中期均线 × 该倍数才买")
    parser.add_argument("--dev-sell-min", type=float, default=0.0,
                        help="卖出下限：收盘 ≥ 中期均线 × 该倍数即清仓（0=不启用）")
    parser.add_argument("--trend-exit-ma", type=int, default=0,
                        help="持仓收盘跌破该均线即清仓（0=不启用）；盯当日均线，非建仓日静态止损价")
    parser.add_argument("--no-rank", dest="rank_by_upside", action="store_false",
                        help="空间只作阈值不作排序：合格集内按代码中性排序，不优先买最便宜的")
    parser.add_argument("--trend-ma", nargs="+", type=int, default=[20, 60],
                        help="走势触发的均线，如 `20 60` 表示 收盘>MA20>MA60；`5 20` 表示 收盘>MA5>MA20；单个值表示只要求站上该均线")
    parser.add_argument("--sell-line", type=float, default=0.0,
                        help="减持线（P/V），缺省 1+w；设为 1.30 即涨到 30%% 溢价才减持")
    parser.add_argument("--trend-tranche", action="store_true",
                        help="走势组改为分批建仓：只要当日仍满足均线与估值条件就按 x%% 继续买入")
    parser.add_argument("--label-suffix", default="")
    args = parser.parse_args()

    print(f"载入…（逐日估值状态、行情、除权除息、均线）")
    universe = load_universe(args.universe_file) if args.universe_file else None
    states = load_states(args.daily_states,
                         {c for _d, m in universe for c in m} if universe else None)
    prices = load_prices({r[0] for rows in states.values() for r in rows})
    actions = load_actions()
    names, benchmark, risk_free = load_names(), load_benchmark(), load_risk_free()
    mas = {code: moving_averages(series) for code, series in prices.items()}
    lows = {code: new_low_flags(series) for code, series in prices.items()}
    day_lists = {code: sorted(series) for code, series in prices.items()}
    day_pos = {code: {d: i for i, d in enumerate(ds)} for code, ds in day_lists.items()}
    corr = Correlations(daily_returns(prices, actions), args.corr_window) if args.max_corr else None
    covered = sorted(states)
    print(f"  逐日状态 {sum(len(v) for v in states.values()):,} 行｜"
          f"{covered[0]} ~ {covered[-1]}｜行情 {len(prices)} 只｜"
          f"基准 {'沪深300 ' + str(len(benchmark)) + ' 日' if benchmark else '**缺**'}")
    if universe:
        sizes = [len(m) for _d, m in universe]
        print(f"  **时点股票库**：{len(universe)} 档｜{universe[0][0]} 起生效｜"
              f"每档 {min(sizes)}~{max(sizes)} 只｜并集 {len({c for _d, m in universe for c in m}):,} 只")
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
                     + (f"_corr{args.max_corr:g}" if args.max_corr else "")
                     + ("_tranche" if args.trend_tranche else "")
                     + (f"_ma{'-'.join(map(str,args.trend_ma))}" if args.trend_ma != [20, 60] else "")
                     + (f"_sl{args.sell_line:g}" if args.sell_line else "")
                     + (f"_xma{args.trend_exit_ma}" if args.trend_exit_ma else "")
                     + ("_norank" if not args.rank_by_upside else "")
                     + (f"_{args.entry_mode}" if args.entry_mode != "trend" else "")
                     + (f"_dsell{args.dev_sell_min:g}" if args.dev_sell_min else "")
                     + (f"_hs{args.hold_strong}{len(args.hold_strong_ma)}" if args.hold_strong != "off" else "")
                     + (f"_{args.rank_mode[:1]}{args.quantile_window or 'all'}" if args.rank_mode != "pv" else "")
                     + (f"_{args.tier_mode}" if args.tier_mode != "none" else "")
                     + ("_minup" if args.min_upside else "")
                     + (f"_cap{args.position_cap:g}" if args.position_cap else "")
                     + (f"_only{args.only_tiers}" if args.only_tiers else "")
                     + args.label_suffix)
            result = run(strategy, x / 100.0, states, prices, actions, mas,
                         args.since, args.until, args.capital, width=width, tiers=tiers,
                         use_mos=args.use_mos, price_stop=args.price_stop,
                         value_stop=args.value_stop, stop_ma=args.stop_ma,
                         trend_stop=args.trend_stop, entry_filter=args.entry_filter,
                         lump_sum=args.lump_sum / 100.0, swap=args.swap,
                         swap_margin=args.swap_margin, max_positions=args.max_positions,
                         lows=lows, day_index=(day_lists, day_pos),
                         max_corr=args.max_corr, corr=corr, tier_mode=args.tier_mode,
                         scan_depth=args.scan_depth,
                         min_upside=(dict(zip(("L1", "L2", "L3"), args.min_upside))
                                     if args.min_upside else None),
                         position_cap=args.position_cap,
                         only_tiers={t.strip() for t in args.only_tiers.split(",") if t.strip()} or None,
                         universe=universe, trend_tranche=args.trend_tranche,
                         trend_ma=tuple(args.trend_ma),
                         sell_line_override=args.sell_line or None,
                         trend_exit_ma=args.trend_exit_ma,
                         rank_by_upside=args.rank_by_upside, entry_mode=args.entry_mode,
                         dev_ma=args.dev_ma, dev_buy_max=args.dev_buy_max,
                         dev_sell_min=args.dev_sell_min, hold_strong=args.hold_strong,
                         hold_strong_ma=tuple(args.hold_strong_ma), rank_mode=args.rank_mode,
                         quantile_window=args.quantile_window,
                         quantile_min_obs=args.quantile_min_obs)
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
