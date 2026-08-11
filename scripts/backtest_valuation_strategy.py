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
import bisect
import csv
import math
import statistics
import sys
import collections
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

DAILY_STATES = ROOT / "data/processed/a_share_historical_valuation_daily.csv"
OHLCV_DIR = ROOT / "data/raw/ohlcv"
RESEARCH_DIR = ROOT / "data/raw/research_reports"
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


class ResearchGate:
    """卖方研报的**预期方向门槛**（用户 2026-08-09：「只有近期研报预期在增长或几乎不变的公司才能买入」）。

    数据边界（决定了这个门槛能测多长，见 `fetch_a_share_research_reports.py` 文件头）
    ------------------------------------------------------------------------------
    * 研报全市场覆盖**始于 2017-01**；
    * **预测 EPS 字段只有 2024 年之后的研报才有值**，2017-2023 全空。

    因此两个口径的可测窗口完全不同，**必须分开报**：

    ``rating``  评级方向。近 `window` 天研报的 `emRatingValue` 均值 vs 前一个 `window`
                天的均值（0=中性 1=持有 2=增持 3=买入）。均值下滑超过 `tol` 即拦截。
                **2018 起可测**（需前置一个窗口做基期）。
    ``nodown``  近 `window` 天内出现过评级下调（`rating_change==1`）即拦截。比 ``rating``
                更硬，只认「有机构明确下调」这一件事，不受覆盖机构结构变化影响。
    ``target``  目标价方向。近窗口目标价中位数 vs 前窗口中位数，跌幅超 `tol` 即拦截。
                填充率 36% 且**贯穿 2017-2026**，是全窗口唯一可用的「预期水平」代理
                （预测 EPS 只有 2024+）。**必须做送转折算**——10 转 10 会把目标价腰斩，
                不折算就会被读成一次 −50% 的下修。折算办法见 `load_research`。
    ``eps``     前瞻 EPS 修正。`fwd12 = TY×(1−f) + NY×f`，`f` 为发布日在当年的进度——
                TY 指**发布当年**（2025-11 的茅台研报 TY≈76.5／NY≈81，12 月被下修到 72.7），
                跨年时按进度加权可保持连续，避免 12 月→1 月的财年标签跳变被误读成修正。
                取窗口内中位数比前窗口中位数，跌幅超 `tol` 即拦截。**仅 2025 起可测**。

    `missing` 决定「无研报覆盖」怎么办。**这一项会改变门槛的性质**：`block` 会把它变成
    一个隐含的规模／关注度过滤器（小盘股常年零覆盖），`pass` 才是纯粹的预期方向门槛。
    默认 `pass`——只在**有证据表明预期被下修**时才拦，没有证据不等于坏消息。
    """

    def __init__(self, ratings, downgrades, forecasts, targets=None, window: int = 180,
                 tol: float = 0.0, missing: str = "pass", permute: int = 0):
        self.ratings, self.downgrades, self.forecasts = ratings, downgrades, forecasts
        self.targets = targets or {}
        self.window, self.tol, self.missing = window, tol, missing
        self.blocked = collections.Counter()
        # 安慰剂：把每只股票的研报序列**按代码序错位 `permute` 位**。拦截强度、时间分布、
        # 覆盖稀疏性全都保留，唯独抹掉「这条信号说的是这家公司」。若安慰剂同样能提高收益，
        # 则增益来自「少买／被动持币」的机械效果，与研报内容无关。
        self.permute = {}
        if permute:
            codes = sorted(set(self.ratings) | set(self.targets) | set(self.downgrades))
            self.permute = {c: codes[(i + permute) % len(codes)] for i, c in enumerate(codes)} if codes else {}

    def _key(self, code: str) -> str:
        return self.permute.get(code, code)

    @staticmethod
    def _shift(day: str, days: int) -> str:
        return (date.fromisoformat(day) - timedelta(days=days)).isoformat()

    @staticmethod
    def _slice(series, lo: str, hi: str):
        """`series` 为按日期升序的 [(date, value), …]；取 **lo < date < hi，两端都开**。

        右端开区间是刻意的：研报的 `publishDate` 只到日，无从判断它在当日开盘前还是收盘后
        发布，而回测按收盘价成交。把当日研报排除掉，最多损失一天新鲜度，却能让「不含未来」
        这件事**无需辩护**。
        """
        i = bisect.bisect_right(series, (lo, float("inf")))
        j = bisect.bisect_left(series, (hi, float("-inf")))
        return [v for _, v in series[i:j]]

    def allows(self, mode: str, code: str, day: str) -> bool:
        mid, start = self._shift(day, self.window), self._shift(day, 2 * self.window)
        code = self._key(code)
        if mode in ("rating", "both"):
            series = self.ratings.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent:
                if self.missing == "block":
                    self.blocked["无覆盖"] += 1
                    return False
            elif prior and (statistics.fmean(recent) - statistics.fmean(prior)) < -self.tol:
                self.blocked["评级下滑"] += 1
                return False
        if mode == "nodown":
            series = self.downgrades.get(code)
            if series and self._slice(series, mid, day):
                self.blocked["评级下调"] += 1
                return False
            if self.missing == "block" and not (self.ratings.get(code)
                                                and self._slice(self.ratings[code], mid, day)):
                self.blocked["无覆盖"] += 1
                return False
        if mode in ("target", "both"):
            series = self.targets.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent or not prior:
                if self.missing == "block":
                    self.blocked["无目标价"] += 1
                    return False
            elif statistics.median(prior) > 0 and \
                    statistics.median(recent) / statistics.median(prior) - 1 < -self.tol:
                self.blocked["目标价下修"] += 1
                return False
        if mode == "eps":
            series = self.forecasts.get(code)
            recent = self._slice(series, mid, day) if series else []
            prior = self._slice(series, start, mid) if series else []
            if not recent or not prior:
                if self.missing == "block":
                    self.blocked["无预测"] += 1
                    return False
            elif statistics.median(prior) > 0 and \
                    statistics.median(recent) / statistics.median(prior) - 1 < -self.tol:
                self.blocked["预测下修"] += 1
                return False
        return True


def load_research(codes: set[str] | None = None, directory: Path | None = None, actions=None):
    """读研报原始档，装配成四张按日期升序的时点表。**只保留 publish_date，绝不引用当前一致预期。**

    目标价的送转折算：令 `C(d) = ∏(1+ratio)`（该股在 d 之前所有除权的送转比例连乘），
    则 `aim × C(d)` 在同一只股票内部是**同一把尺子**——发生 10 转 10 时，除权前定的
    目标价 100 与除权后定的 50 都会折成同一个数，不再产生假的 −50% 下修。
    """
    factors: dict[str, list[tuple[str, float]]] = {}
    for code, events in (actions or {}).items():
        cumulative, series = 1.0, []
        for day in sorted(events):
            cumulative *= (1.0 + events[day][1])
            series.append((day, cumulative))
        if series:
            factors[code] = series

    def factor_at(code: str, day: str) -> float:
        series = factors.get(code)
        if not series:
            return 1.0
        i = bisect.bisect_left(series, (day, float("-inf")))
        return series[i - 1][1] if i else 1.0

    ratings: dict[str, list[tuple[str, float]]] = defaultdict(list)
    downgrades: dict[str, list[tuple[str, float]]] = defaultdict(list)
    forecasts: dict[str, list[tuple[str, float]]] = defaultdict(list)
    targets: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for path in sorted((directory or RESEARCH_DIR).glob("reports_*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code, day = row["security_code"], row["publish_date"]
                if not code or len(day) != 10 or (codes is not None and code not in codes):
                    continue
                value = _num(row.get("rating_value"))
                if value is not None:
                    ratings[code].append((day, value))
                if (row.get("rating_change") or "").strip() == "1":
                    downgrades[code].append((day, 1.0))
                this_year, next_year = _num(row.get("predict_this_year_eps")), _num(row.get("predict_next_year_eps"))
                if this_year and next_year and this_year > 0 and next_year > 0:
                    fraction = (date.fromisoformat(day).timetuple().tm_yday - 1) / 365.0
                    forecasts[code].append((day, this_year * (1 - fraction) + next_year * fraction))
                aim = _num(row.get("aim_price"))
                if aim and aim > 0:
                    targets[code].append((day, aim * factor_at(code, day)))
    for table in (ratings, downgrades, forecasts, targets):
        for series in table.values():
            series.sort()
    return dict(ratings), dict(downgrades), dict(forecasts), dict(targets)


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


def load_opens(codes: set[str] | None = None) -> dict[str, dict[str, float]]:
    """逐票开盘价。仅 `--exec-delay 1 --exec-price open` 用得到，故按需载入。"""
    out: dict[str, dict[str, float]] = {}
    for path in sorted(OHLCV_DIR.glob("*.csv")):
        if path.stem.startswith("INDEX_") or (codes is not None and path.stem not in codes):
            continue
        series = {}
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                value = _num(row.get("open"))
                if value and value > 0:
                    series[row["date"]] = value
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
    debt: float = 0.0                 # 融资余额（含已计提利息）
    interest_paid: float = 0.0        # 累计利息

    def gross(self, prices: dict[str, float]) -> float:
        """总资产 = 现金 + 持仓市值。担保比例的分子。"""
        total = self.cash
        for code, lot in self.lots.items():
            price = prices.get(code)
            if price:
                total += lot.shares * price
        return total

    def equity(self, prices: dict[str, float]) -> float:
        """**净资产 N = 总资产 − 融资负债**（§9.7.1.1）。无杠杆时与旧口径完全一致。"""
        return self.gross(prices) - self.debt

    def margin_ratio(self, prices: dict[str, float]) -> float:
        """担保比例 = 总资产 ÷ 融资负债。无负债时为无穷大。"""
        return float("inf") if self.debt <= 0 else self.gross(prices) / self.debt


def credit_room(portfolio: Portfolio, limit: float) -> float:
    """还能再融多少。"""
    return max(0.0, limit - portfolio.debt)


def buying_power(portfolio: Portfolio, limit: float) -> float:
    """可用于买入的总金额 = 现金 + 剩余授信。"""
    return portfolio.cash + credit_room(portfolio, limit)


def draw_credit(portfolio: Portfolio, need: float, limit: float) -> float:
    """现金不足时融资补足，返回实际可动用的现金额。"""
    if portfolio.cash >= need:
        return need
    draw = min(need - portfolio.cash, credit_room(portfolio, limit))
    if draw > 0:
        portfolio.cash += draw
        portfolio.debt += draw
    return min(need, portfolio.cash)


def repay_debt(portfolio: Portfolio, ratchet: bool) -> None:
    """融资棘轮：卖出回笼的资金**必须先偿还融资**，不得循环滚入下一笔买入。"""
    if not ratchet or portfolio.debt <= 0 or portfolio.cash <= 0:
        return
    pay = min(portfolio.cash, portfolio.debt)
    portfolio.cash -= pay
    portfolio.debt -= pay


def force_liquidate(portfolio: Portfolio, day: str, marks: dict[str, float],
                    maintenance: float, recover_to: float, ledger: list | None) -> dict:
    """担保比例跌破维持线时的强制平仓。

    按持仓市值从大到小卖，直到担保比例回到 `recover_to`（警戒线）或无券可卖。
    **A 股实盘是券商代为强平、不由持有人择时**，故这里不看 P/V、不看走势，只看市值。
    """
    sold_value = 0.0
    order = sorted(portfolio.lots.items(),
                   key=lambda kv: -(kv[1].shares * marks.get(kv[0], 0.0)))
    for code, lot in order:
        if portfolio.margin_ratio(marks) >= recover_to or portfolio.debt <= 0:
            break
        price = marks.get(code)
        if not price:
            continue
        proceeds = lot.shares * price
        sold_value += proceeds
        close_lot(portfolio, code, day, price, "强制平仓", ledger)
        pay = min(portfolio.cash, portfolio.debt)
        portfolio.cash -= pay
        portfolio.debt -= pay
    return {"sold": sold_value, "ratio_after": portfolio.margin_ratio(marks)}


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


def lot_ratio_ready(counters: dict, code: str, lot_value: float, tranche: float) -> bool:
    """§9.7.3 比例冷却（用户 2026-08-10 指令）：一手价值是一档的 `x` 倍时，**成交一手后跳过随后
    `round(x) − 1` 次合格机会**，即每 `round(x)` 次合格才动一手。

    为什么按「合格次数」而不是自然日：冷却的目的是让**平均速度等于一档/次**，而合格机会本身
    是不连续的（走势条件断了就不合格）。按日历天计的话，一只票停牌或走势坏掉十天，冷却期照走，
    复合格当天就能立刻成交——冷却等于没起作用。原 `--min-lot-cooldown 5` 即此形态。

    取 `round(x)` 而非 `floor(x)+1`：目标是平均速度 ≈ 一档/次，`round` 的偏差 <5%
    （茅台 x=9.07 → 每 9 次一手 = 1.008 档/次；春风动力 x=2.04 → 每 2 次一手 = 1.02 档/次）。
    若按字面「跳过 x 次」则为每 10 次/每 3 次，速度掉到 0.91/0.68 档，对贵股系统性欠配。

    买卖共用一个计数器：同一只票不可能同日既在买入清单又在减持清单。
    """
    if tranche <= 0 or lot_value <= 0:
        return False
    if counters.get(code, 0) > 0:
        counters[code] -= 1
        return False
    counters[code] = max(1, round(lot_value / tranche)) - 1
    return True


def sell_shares(target: float, held: float, price: float, lot_size: int) -> float:
    """分批卖出的股数：按手向下取整。**剩余不足一手则整笔卖出**——A 股允许零股卖出，
    但不允许留着买不回来的零头当仓位管理。返回 0 表示本次不动。"""
    if not lot_size:
        return min(held, target)
    want = min(held, target)
    lots_n = int(want // lot_size)
    if lots_n <= 0:
        return 0.0
    shares = lots_n * lot_size
    return held if held - shares < lot_size else shares


def log_partial_sell(ledger: list | None, day: str, code: str, shares: float,
                     price: float, reason: str) -> None:
    """部分减持也要进流水。**此前只有 `close_lot` 记账**，故流水缺掉全部「减一档」，
    拿它重建逐日持仓会得到系统性偏高的股数——实测重建出的前三大合计可达 123.8%，
    而回测是无杠杆的。流水是「人工核对用」的凭证，缺一半就不能用来对账。
    """
    if ledger is None:
        return
    ledger.append({"date": day, "security_code": code, "action": "卖出",
                   "shares": f"{shares:.0f}", "price": f"{price:.3f}",
                   "amount": f"{shares * price:.0f}", "pv_ratio": "",
                   "intrinsic_value": "", "reason": reason})


def close_lot(portfolio: Portfolio, code: str, day: str, price: float, reason: str,
              ledger: list | None = None) -> None:
    lot = portfolio.lots.pop(code)
    if ledger is not None:
        ledger.append({"date": day, "security_code": code, "action": "卖出",
                       "shares": f"{lot.shares:.0f}", "price": f"{price:.3f}",
                       "amount": f"{lot.shares * price:.0f}", "pv_ratio": "",
                       "intrinsic_value": "", "reason": reason})
    portfolio.cash += lot.shares * price
    lot.proceeds += lot.shares * price
    lot.shares = 0.0
    lot.exit_date, lot.exit_reason = day, reason
    lot.sells += 1
    portfolio.closed.append(lot)


# ------------------------------------------------------------------ 回测
def run(strategy: str, x: float, states, prices, actions, mas, since: str, until: str,
        capital: float, width: float = 0.10, tiers: dict[str, str] | None = None,
        credit_ratio: float = 0.0, credit_cap: float = 0.0, margin_rate: float = 0.0,
        maintenance: float = 1.30, recover_to: float = 1.50, margin_ratchet: bool = False,
        use_mos: bool = False, price_stop: bool = False, value_stop: float = 0.0,
        stop_ma: int = 20, trend_stop: bool = True, entry_filter: str = "none",
        lump_sum: float = 0.0, swap: bool = False, swap_margin: float = 0.10,
        max_positions: int = MAX_POSITIONS, lows=None, day_index=None,
        max_corr: float = 0.0, corr=None, tier_mode: str = "none",
        scan_depth: int = 40, min_upside: dict[str, float] | None = None,
        position_cap: float = 0.0, only_tiers: set[str] | None = None,
        universe: list[tuple[str, set[str]]] | None = None,
        trend_tranche: bool = False, trend_ma: tuple[int, ...] = (20, 60),
        trend_tol: float = 0.0, exec_delay: int = 0, exec_price: str = "close",
        sell_trend_ma: tuple[int, ...] = (),
        liquidate_ma: int = 0, liquidate_days: int = 3,
        opens: dict[str, dict[str, float]] | None = None,
        sell_line_override: float | None = None, trend_exit_ma: int = 0,
        rank_by_upside: bool = True, entry_mode: str = "trend", dev_ma: int = 60,
        dev_buy_max: float = 1.10, dev_sell_min: float = 0.0,
        hold_strong: str = "off", hold_strong_ma: tuple[int, ...] = (),
        rank_mode: str = "pv", quantile_window: int = 0,
        quantile_min_obs: int = 250, research_gate: str = "off",
        research: "ResearchGate | None" = None,
        swap_bypass_corr: bool = False, stats: dict | None = None,
        cluster_swap: bool = False, cluster_delta: float = 0.85,
        cluster_min_upside: float = 0.20, swap_partial: bool = False,
        lot_size: int = 0, rebuy: str = "off", ledger: list | None = None,
        min_lot_cooldown: int = 0, lot_ratio_cooldown: bool = False) -> dict:
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
    stats = stats if stats is not None else collections.Counter()
    # 割肉后的「欠账」：被 `trend_exit_ma` 清掉的股数记在此处，等该股重新满足买入条件时
    # 按 `rebuy` 口径补回。**lump=一次性买回相同股数；gradual=交回常规定投**（即不记账）。
    cut_shares: dict[str, float] = {}
    last_buy: dict[str, str] = {}      # 每股最近一次买入日，供「买不起一档就买一手」的冷却期判定
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

    def strong_bull(code: str, day: str) -> bool:
        """完全多头排列：MA20>MA60>MA120>MA240（窗口可配）。**当日可判、无前视**。

        用于豁免强势股的减持与换出——**根因是报告期之间 `V` 冻结**：中际旭创 2025-05-26
        收盘 92.4／V=108.2／P/V=0.85，三周后收盘 125.2 而 V 仍是 108.2，P/V 被价格单方面
        推到 1.16 触发清空；此后该股再涨 560%。均线排列与内在价值无关，故可独立成立。
        """
        if not hold_strong_ma:
            return False
        ma = mas.get(code, {}).get(day, {})
        if not all(w in ma for w in hold_strong_ma):
            return False
        return all(ma[a] > ma[b] for a, b in zip(hold_strong_ma, hold_strong_ma[1:]))

    def buy_line(code: str) -> float:
        if use_mos:
            return 1.0 - MOS_BY_TIER.get(tiers.get(code, DEFAULT_TIER), width)
        return 1.0 - width

    prev_day = None
    margin_events: list[dict] = []
    lot_counters: dict[str, int] = {}   # §9.7.3 比例冷却，买卖共用
    min_ratio, min_ratio_day = float("inf"), ""
    credit_limit = 0.0
    prev_trading = {n: d for d, n in zip(days, days[1:])}
    below_ma_run: dict[str, int] = {}      # 连续跌破 `liquidate_ma` 的天数，逐日累计
    for day in days:
        apply_corporate_actions(portfolio, day, actions)

        # ---- 融资计息（不需要价格，故放在循环头）----
        if portfolio.debt > 0 and margin_rate > 0 and prev_day:
            accrue = portfolio.debt * margin_rate * max(1, _days_between(prev_day, day)) / 365.0
            portfolio.debt += accrue
            portfolio.interest_paid += accrue
        prev_day = day
        if universe:
            while uni_idx < len(universe) and universe[uni_idx][0] <= day:
                members = universe[uni_idx][1]
                uni_idx += 1
        # 成交时序（用户 2026-08-10）：`exec_delay=1` = 「T 日收盘算信号、T+1 日成交」。
        # **实现为「移信号」而非「移价格」**——在 T 日用 T−1 的判据、在 T 日成交，
        # 于是现金、股数、盯市全部落在同一天。**先前按「记在 T 日、用 T+1 的价」实现是错的**：
        # 花的钱是 T+1 的价而持仓按 T 日收盘盯市，跳空大的日子会在净值曲线上造出一对假涨跌，
        # 2015-06 崩盘段实测把最大回撤由 33% 放大到 56%——那是记账错配，不是执行代价。
        sig_day = prev_trading.get(day) if exec_delay else day
        if sig_day is None:
            equity_curve.append((day, portfolio.equity({}), portfolio.cash, 0, portfolio.debt,
                                 portfolio.margin_ratio({})))
            continue
        today = {code: (close, value, ratio) for code, close, value, ratio in states[sig_day]}
        # `liquidate_ma` 的连续天数计数（用户 2026-08-10）：**对全池逐日累计**，不能只对持仓算
        # ——一只票可能在计数中途被卖光又买回，只对持仓算会把计数错误地清零。
        if liquidate_ma:
            for c, r in today.items():
                ma_l = mas.get(c, {}).get(sig_day, {}).get(liquidate_ma)
                if ma_l is None:
                    below_ma_run[c] = 0
                else:
                    below_ma_run[c] = below_ma_run.get(c, 0) + 1 if r[0] < ma_l else 0
        scores = {code: score_of(code, r[2]) for code, r in today.items()} if rank_mode != "pv" else {}
        if rank_mode != "pv":
            for code, r in today.items():
                push_pv(code, r[2])
        # 停牌股当日无价，**必须沿用最后成交价**——否则它会整只从净值里消失，
        # 复牌当天再凭空出现，资金曲线上是一对假的暴跌+暴涨。
        marks = {}
        for code in portfolio.lots:
            price = prices.get(code, {}).get(day) or (today[code][0] if code in today else None)
            if price:
                last_price[code] = price
            if code in last_price:
                marks[code] = last_price[code]
        # ---- 成交价口径（用户 2026-08-10）：`exec_delay=1` 表示「T 日收盘算信号、T+1 日成交」。
        # **只改成交价，不改判据**——合格集、`P/V`、均线、盯市净值一律仍用 T 日收盘，
        # 因为信号本来就定义在 T 日收盘上；改的只是这笔单实际以什么价格成交。
        # T+1 无价（停牌/最后一日）时回落到 T 日收盘并计数，不静默丢弃该笔。
        def fill_price(code: str, fallback: float | None) -> float | None:
            if exec_delay == 0:
                return fallback                      # 现行口径：成交价即 T 日收盘
            src = (opens or {}) if exec_price == "open" else prices
            got = src.get(code, {}).get(day)
            if got and got > 0:
                return got
            stats["成交日无价·回落信号日收盘"] += 1
            return fallback

        # ---- 融资：按当日净资产重定授信额度，并查担保比例 ----
        if credit_ratio > 0:
            net_now = portfolio.equity(marks)
            # 授信随净资产变动、封顶 credit_cap；**已用额度不因限额下调而被强制归还**，
            # 只是不能再新增——现实中券商下调授信也是这个次序。
            credit_limit = max(portfolio.debt, min(max(net_now, 0.0) * credit_ratio, credit_cap))
            ratio_now = portfolio.margin_ratio(marks)
            if portfolio.debt > 0 and ratio_now < min_ratio:
                min_ratio, min_ratio_day = ratio_now, day
            if portfolio.debt > 0 and ratio_now < maintenance:
                res = force_liquidate(portfolio, day, marks, maintenance, recover_to, ledger)
                marks = {c: p for c, p in marks.items() if c in portfolio.lots}
                margin_events.append({
                    "date": day, "ratio_before": ratio_now, "ratio_after": res["ratio_after"],
                    "sold": res["sold"], "equity_before": net_now,
                    "equity_after": portfolio.equity(marks), "debt_after": portfolio.debt,
                })
                stats["**爆仓·强制平仓**"] += 1

        equity = portfolio.equity(marks)
        if equity <= 0:
            stats["**穿仓·净资产归零**"] += 1
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
            lot, price = portfolio.lots[code], fill_price(code, marks.get(code))
            if not price:
                continue
            ratio = today.get(code, (None, None, None))[2]
            # 移出股票库 → **逐步清仓**（用户 2026-08-08：「对于被移除股票库的公司，逐步清仓」）。
            # 按与减持同一速度卖，不一次性砸出——一年一次的换库若全额出清，会在每年 5 月
            # 制造一次集中抛售，测出来的是流动性冲击而不是规则优劣。
            if members is not None and code not in members:
                shares = sell_shares(budget / price, lot.shares, price, lot_size)
                if (not shares and lot_ratio_cooldown and lot_size
                        and lot.shares >= lot_size
                        and lot_ratio_ready(lot_counters, code, price * lot_size, budget)):
                    shares = lot_size if lot.shares - lot_size >= lot_size else lot.shares
                    stats["高价股·按手减持"] += 1
                if shares > 0:
                    if shares >= lot.shares * 0.999:
                        turnover += lot.shares * price
                        close_lot(portfolio, code, day, price, ledger=ledger, reason="移出股票库·逐步清仓")
                    else:
                        log_partial_sell(ledger, day, code, shares, price, "移出股票库·减一档")
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
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"偏离MA{dev_ma}达{dev_sell_min:.0%}清仓")
                    sell_count += 1
                    continue
            if trend_exit_ma:
                ma_now = mas.get(code, {}).get(day, {})
                if trend_exit_ma in ma_now and price < ma_now[trend_exit_ma]:
                    if rebuy == "lump":
                        cut_shares[code] = cut_shares.get(code, 0.0) + lot.shares
                        stats["割肉记账"] += 1
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"跌破MA{trend_exit_ma}清仓")
                    sell_count += 1
                    continue
            if ((strategy == "trend" and trend_stop) or price_stop) and lot.entry_stop and price < lot.entry_stop:
                turnover += lot.shares * price     # 必须在 close_lot 之前取——它会把 shares 清零
                close_lot(portfolio, code, day, price, ledger=ledger, reason=f"跌破建仓日MA{lot.entry_stop_ma}止损")
                sell_count += 1
                continue
            # 基本面退出：内在价值自峰值回落超阈值即清仓。**盯 V 不盯价**，故一只票可以
            # 在股价没怎么跌的时候就被卖掉——那正是「业绩塌了但市场还没反应」的情形。
            if value_stop and lot.peak_intrinsic > 0:
                current_value = today.get(code, (None, None, None))[1]
                if current_value and current_value <= lot.peak_intrinsic * (1 - value_stop):
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"内在价值自峰值回落≥{value_stop:.0%}")
                    sell_count += 1
                    continue
            # 强势多头豁免减持：空间缩小不卖，等趋势自己走坏或财报更新带改变格局。
            if (hold_strong in ("sell", "both") and strong_bull(code, day)):
                continue
            # `sell_trend_ma`（用户 2026-08-10）：**卖出端的右侧化**。买入端要求
            # `收盘 > MA20 > MA60`（贵了才卖不够，还要等趋势真的坏掉），卖出端原本是纯估值触发
            # ——`P/V ≥ 减持线` 当日即开始按一档减。本参数把它改为**还须同时呈空头排列**才减，
            # 例如 `(5, 20)` 即 `收盘 < MA5 < MA20`。空元组 = 原行为。
            # **只闸这一条路径**：出 §5 名单的清仓与换仓卖出不受影响——前者是基本面退出、
            # 后者是资金驱动，都与趋势无关；闸住它们等于在该走的时候不走。
            # 判据用**信号日**的收盘与均线（与买入端同源），不是成交价。
            # `liquidate_ma` / `liquidate_days`（用户 2026-08-10）：**贵 + 中期趋势确认走坏 → 一次清仓**。
            # 与 `--trend-exit-ma` 的两点区别：①**须同时 `P/V ≥ 减持线`**（只对已经贵的票生效，
            # 便宜票跌破年线是加仓机会不是清仓理由）；②**要求连续 N 日**跌破，不是单日破线，
            # 以滤掉一次性插针。它在减一档之前判——既然要清，就不必先减一档。
            if (liquidate_ma and ratio is not None and ratio >= sell_line
                    and below_ma_run.get(code, 0) >= liquidate_days):
                turnover += lot.shares * price
                close_lot(portfolio, code, day, price, ledger=ledger,
                          reason=f"P/V≥{sell_line:.2f}且连续{liquidate_days}日破MA{liquidate_ma}·清仓")
                sell_count += 1
                stats[f"贵+破MA{liquidate_ma}·一键清仓"] += 1
                continue
            if ratio is not None and ratio >= sell_line and sell_trend_ma:
                sig_close = today.get(code, (None,))[0]
                ma_s = mas.get(code, {}).get(sig_day, {})
                if not sig_close or not all(w in ma_s for w in sell_trend_ma):
                    continue                       # 均线不全 → 不减，等数据齐
                seq = [sig_close] + [ma_s[w] for w in sell_trend_ma]
                if not all(a < b for a, b in zip(seq, seq[1:])):
                    stats["减持被走势闸门挡下"] += 1
                    continue
            if ratio is not None and ratio >= sell_line:
                stats["P/V≥减持线·减一档"] += 1
                shares = sell_shares(budget / price, lot.shares, price, lot_size)
                if (not shares and lot_ratio_cooldown and lot_size
                        and lot.shares >= lot_size
                        and lot_ratio_ready(lot_counters, code, price * lot_size, budget)):
                    shares = lot_size if lot.shares - lot_size >= lot_size else lot.shares
                    stats["高价股·按手减持"] += 1
                if shares <= 0:
                    continue
                if shares >= lot.shares * 0.999:
                    turnover += lot.shares * price
                    close_lot(portfolio, code, day, price, ledger=ledger, reason=f"P/V≥{sell_line:.2f}清空")
                else:
                    log_partial_sell(ledger, day, code, shares, price, f"P/V≥{sell_line:.2f}·减一档")
                    lot.shares -= shares
                    portfolio.cash += shares * price
                    lot.proceeds += shares * price
                    lot.sells += 1
                    turnover += shares * price
                sell_count += 1

        # ---- 买入：合格集为空则持币（用户 2026-08-08 裁定），**不硬凑前十**
        pool = states[sig_day] if members is None else [r for r in states[sig_day] if r[0] in members]
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
        # 研报预期门槛：**卡在所有买入路径的上游**——`eligible` 同时供定投买入与换仓选目标，
        # 在此过滤即等于「每次买入节点都要过一次」，加仓也一样受约束（用户 2026-08-09 原话）。
        if research_gate != "off" and research is not None:
            eligible = [r for r in eligible if research.allows(research_gate, r[0], day)]
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
            # `trend_tol`（用户 2026-08-10）：走势条件的容差。判据由 `收盘 > MA20` 放宽为
            # `收盘 > MA20 × (1 − tol)`，`MA20 > MA60` 同样处理。**动机是执行时点差而非选股**——
            # 信号定义在收盘，而用户在盘中下单，收盘前跨越均线的票在盘中看不到（判例：
            # 特宝生物 2026-08-10 当日 +4.31%，尾盘才收在 MA20 上方 +0.26%）。
            # **注意容差不消除边界，只是把边界挪个位置**：新线附近照样有票在盘中与收盘之间翻转。
            # 本参数能回答的是「放松到这个程度策略本身还成不成立」，不是「能不能消除时点差」。
            k = 1.0 - trend_tol
            eligible = [r for r in eligible
                        if (ma := mas.get(r[0], {}).get(sig_day)) and all(w in ma for w in trend_ma)
                        and r[1] > ma[trend_ma[0]] * k
                        and (len(trend_ma) < 2 or ma[trend_ma[0]] > ma[trend_ma[1]] * k)]
        if entry_filter == "stabilized" and lows is not None:
            eligible = [r for r in eligible
                        if stabilized(lows.get(r[0], {}), day_index[0].get(r[0], []),
                                      day_index[1].get(r[0], {}), day)]
        # ---- 簇内升级模式（用户 2026-08-09 提出的完整方案）
        # 与既有「换仓 + 相关性过滤」的根本差别：**相关性在这里是「替换谁」的判据，
        # 不是「排除谁」的过滤器**。既有口径下高相关候选会触发卖出**空间最小的持仓**
        # （可能与它毫不相关），等于用分散度换便宜；此处改为卖出**与它同簇的那只**，
        # 敞口结构不变、只把簇内的持仓换成更便宜的一只。持仓个数不设上限，由簇的数量自然决定。
        #
        # 每日三步：
        #   ① 备选 = 空间 ≥ `cluster_min_upside` 的合格候选（空间作门槛，不作排序上限）
        #   ② 在备选内部两两去相关（**不看持仓**），得到当日买入备选
        #   ③ 逐个决定：与某持仓相关性 > `cluster_delta` 且更便宜 → 换掉那只；
        #      与任何持仓都不强相关 → 直接建仓或加仓；簇内已有更便宜的 → 本日不买
        if cluster_swap and eligible:
            cands = [r for r in eligible if (1.0 / r[3] - 1.0) >= cluster_min_upside]
            picks: list = []
            for r in cands[:scan_depth]:
                if corr is not None and max_corr and any(
                        (v := corr.get(r[0], q[0], day)) is not None and v > max_corr for q in picks):
                    continue
                picks.append(r)
            final = []
            cluster_reduced: set[str] = set()
            for r in picks:
                code = r[0]
                if code in portfolio.lots:
                    final.append(r)                      # 已持仓：继续加仓
                    continue
                cand_score = scores.get(code, r[3]) if rank_mode != "pv" else r[3]
                kin = []
                if corr is not None:
                    for held in portfolio.lots:
                        if held not in today:
                            continue
                        v = corr.get(code, held, day)
                        if v is not None and v > cluster_delta:
                            kin.append((scores.get(held, today[held][2])
                                        if rank_mode != "pv" else today[held][2], held))
                if not kin:
                    final.append(r)                      # 无同簇持仓：直接建仓
                    continue
                worst_ratio, worst = max(kin)            # 同簇里最贵的那只
                if worst_ratio - cand_score < swap_margin:
                    continue                             # 簇内已有更便宜的，本日不买
                price = fill_price(worst, marks.get(worst))
                if not price:
                    continue
                # v2.78：簇内升级同样支持「减一档」（用户 2026-08-10 澄清口径）。
                # 原实现是整仓卖出，与 v2.74 已否定的换仓整仓卖出同形——两者砸掉的都是
                # §12.3 里正在复利的仓位。`cluster_reduced` 保证同一只每日至多被削一档。
                lot_w = portfolio.lots[worst]
                if swap_partial and worst not in cluster_reduced:
                    shares = sell_shares(budget / price, lot_w.shares, price, lot_size)
                    if (not shares and lot_ratio_cooldown and lot_size
                            and lot_w.shares >= lot_size
                            and lot_ratio_ready(lot_counters, worst, price * lot_size, budget)):
                        shares = lot_size if lot_w.shares - lot_size >= lot_size else lot_w.shares
                    if not shares:
                        continue                     # 一手都减不动 → 本日不升级
                    cluster_reduced.add(worst)
                    if shares < lot_w.shares * 0.999:
                        stats["簇内升级·减一档"] += 1
                        lot_w.shares -= shares
                        portfolio.cash += shares * price
                        lot_w.proceeds += shares * price
                        lot_w.sells += 1
                        turnover += shares * price
                    else:
                        turnover += lot_w.shares * price
                        close_lot(portfolio, worst, day, price, ledger=ledger,
                                  reason=f"同簇升级·余额不足一档清仓：让位给{code}")
                elif swap_partial:
                    continue                         # 本日已削过这只，不重复
                else:
                    turnover += lot_w.shares * price
                    close_lot(portfolio, worst, day, price, ledger=ledger,
                              reason=f"同簇升级：让位给更便宜的{code}")
                sell_count += 1
                final.append(r)
            eligible = final
        # 换仓：想买却买不下（没钱或槽位满）时，把**空间最小**的持仓换成**空间更大**的候选。
        # `swap_margin` 是防抖阈值——两者 P/V 差不到这个数就不换，否则每天的微小排名波动
        # 都会触发一次双边交易。
        # `swap_targets`：本日因「空间更大」而触发了卖出的候选。**换仓块在相关性过滤之前执行**，
        # 故它可以为一只随后被相关性挡掉的候选腾位——卖了却买不进，钱转投下一个不相关的候选。
        # 用户 2026-08-09 追问的正是这个口径。`swap_bypass_corr` 打开后，已经为之腾过位的候选
        # 豁免相关性检查：既然已经付出了卖出的代价，就该买到它。
        swap_targets: set[str] = set()
        reduced_today: set[str] = set()      # 同一只每日最多被换仓减一档，防止一天削十次
        # 簇内升级之后仍保留原换仓作为**兜底**：用户方案里「没有强相关持仓就直接建仓或加仓」
        # 隐含了「有钱」这个前提，而簇内升级是自筹资金的（卖一只买一只），**不产生新增现金**。
        # 缺了兜底，资金打满后组合就冻住——实测换手由 200.9% 塌到 17.6%、买入 2145→474 笔。
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
                price = fill_price(worst, marks.get(worst))
                if not price:
                    break
                # `swap_partial`（用户 2026-08-09）：换仓由**整仓卖出**改为**按定投同速减一档**。
                # **仅在「只差钱、槽位没满」时适用**——槽位满时减仓不腾出槽位，新标的照样买不进
                # （买入循环里 `code not in lots and len(lots) >= max_positions` 会挡下），
                # 只会每天空转地削持仓。故槽位满时仍整仓卖出。
                lot_worst = portfolio.lots[worst]
                partial = swap_partial and len(portfolio.lots) < max_positions and worst not in reduced_today
                shares = (sell_shares(budget / price, lot_worst.shares, price, lot_size)
                          if partial else lot_worst.shares)
                if (partial and not shares and lot_ratio_cooldown and lot_size
                        and lot_worst.shares >= lot_size
                        and lot_ratio_ready(lot_counters, worst, price * lot_size, budget)):
                    shares = (lot_size if lot_worst.shares - lot_size >= lot_size
                              else lot_worst.shares)
                    stats["高价股·按手换仓"] += 1
                if partial and shares < lot_worst.shares * 0.999:
                    stats["换仓·减一档"] += 1
                    lot_worst.shares -= shares
                    portfolio.cash += shares * price
                    lot_worst.proceeds += shares * price
                    lot_worst.sells += 1
                    turnover += shares * price
                    log_partial_sell(ledger, day, worst, shares, price, f"换仓·减一档：让位给{code}")
                    reduced_today.add(worst)
                else:
                    stats["换仓·整仓卖出"] += 1
                    turnover += lot_worst.shares * price
                    close_lot(portfolio, worst, day, price, ledger=ledger, reason=f"换仓：让位给空间更大的{code}")
                sell_count += 1
                swap_targets.add(code)
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
        if max_corr and corr is not None and not cluster_swap:
            chosen, anchors = [], list(portfolio.lots)
            for r in eligible[:scan_depth]:
                if len(chosen) >= max_positions:
                    break
                if r[0] in portfolio.lots:
                    chosen.append(r)          # 已持仓的继续加仓，不受相关性约束
                    continue
                c = [corr.get(r[0], other, day) for other in anchors + [x[0] for x in chosen]]
                if any(v is not None and v > max_corr for v in c):
                    if r[0] in swap_targets:
                        stats["换仓目标被相关性挡下"] += 1
                        if swap_bypass_corr:
                            chosen.append(r)
                            continue
                    continue
                chosen.append(r)
            eligible = chosen

        for code, close, value, ratio in eligible[:max_positions]:
            if buying_power(portfolio, credit_limit) <= 0:
                break
            # 走势组默认一笔建仓（总资产 ÷ 持仓上限）且不加仓；`trend_tranche` 打开后改为
            # **与估值组同一套定投**——只要当日仍满足「P/V 合格 且 收盘>MA20>MA60」就继续买入
            # 总资产 × x%。用户 2026-08-09：「走势满足要求的情况下分批进行建仓」。
            fill = fill_price(code, close) or close
            tranche = trend_tranche and strategy == "trend"
            if ((strategy == "trend" and not tranche) or lump_sum) and code in portfolio.lots:
                continue                      # 一笔建仓：不加仓
            avail = buying_power(portfolio, credit_limit)
            if lump_sum:
                amount = min(equity * lump_sum, avail)
            else:
                amount = min(budget if (strategy == "valuation" or tranche)
                             else equity / max_positions, avail)
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
            # A 股买入必须是 100 股整数倍。`lot_size` 打开后按手向下取整，**买不足一手就跳过**
            # ——这才是真实可执行的口径。一档金额买不起一手的高价股（茅台一手 13 万）会被自然排除，
            # 这不是缺陷而是事实：0.5%% 的定投额度本来就装不下这类标的。
            if lot_size:
                lots_n = int(amount // (fill * lot_size))
                if lots_n <= 0:
                    # 高价股（茅台一手 13 万）一档金额买不起一手。**不因此放弃建仓**，改为
                    # 每次买一手、隔 `min_lot_cooldown` 个交易日再买下一手（用户 2026-08-09 指令）。
                    # 冷却期是必需的：不设的话一手会天天买，等于把该股的定投速度放大到一档以上。
                    # v2.77 起冷却由「自然日」改为「合格次数」（`lot_ratio_ready`，§9.7.3）；
                    # `--min-lot-cooldown` 保留为旧口径，两者互斥，都不给则不建仓（原行为）。
                    if lot_ratio_cooldown:
                        ready = lot_ratio_ready(lot_counters, code, fill * lot_size, budget)
                    else:
                        prior = last_buy.get(code)
                        ready = (min_lot_cooldown
                                 and (prior is None or _days_between(prior, day) >= min_lot_cooldown))
                    if ready and buying_power(portfolio, credit_limit) >= fill * lot_size:
                        lots_n = 1
                        stats["高价股·按手建仓"] += 1
                    else:
                        stats["买不足一手·跳过"] += 1
                        continue
                shares = lots_n * lot_size
                amount = shares * fill
            else:
                shares = amount / fill
            # 割肉买回：**只在该股重新合格的那一天触发一次**，买回被割掉的全部股数（现金不足则买满为止）。
            # 与常规定投的区别是它不受 0.5%% 一档限制——割肉时卖掉的是整仓，补回也应是整仓。
            if rebuy == "lump" and cut_shares.get(code) and code not in portfolio.lots:
                want = cut_shares.pop(code)
                if lot_size:
                    want = int(want // lot_size) * lot_size
                afford = (min(want, buying_power(portfolio, credit_limit) / fill)
                          if fill > 0 else 0.0)
                if lot_size:
                    afford = int(afford // lot_size) * lot_size
                if afford > 0:
                    shares, amount = afford, afford * fill
                    stats["割肉买回"] += 1
            lot = portfolio.lots.get(code)
            if lot is None:
                # 止损价取**成交日**均线。成交日停牌时 `mas[code][day]` 整条缺失，
                # `ma.get(20, 0.0)` 会返回 0，而 `lot.entry_stop` 为 0 时止损分支被 falsy 短路
                # ——**该仓从此永远不受止损约束，且没有任何提示**（§13 第 3 条的静默失效）。
                # 实测 2002 起点 1,697 个周期里有 4 个如此。成交价此时已回落到信号日收盘，
                # 故止损价一并回落到信号日均线，两者同源。
                ma = mas.get(code, {}).get(day) or mas.get(code, {}).get(sig_day, {})
                if not mas.get(code, {}).get(day):
                    stats["成交日无均线·止损价回落信号日"] += 1
                lot = Lot(code=code, entry_date=day, entry_ratio=ratio, entry_value=value,
                          entry_band_low=(1 - width) * value, entry_band_high=(1 + width) * value,
                          entry_upside=value / fill - 1, peak_intrinsic=value)
                lot.entry_stop, lot.entry_stop_ma = entry_stop_price(ma, close, stop_ma)
                portfolio.lots[code] = lot
            lot.shares += shares
            lot.invested += amount
            lot.buys += 1
            draw_credit(portfolio, amount, credit_limit)   # 现金不足即动用授信
            portfolio.cash -= amount
            last_buy[code] = day
            if ledger is not None:
                # **price 必须记 `fill` 不是 `close`**：`close` 是信号日收盘，而这笔单成交在
                # `fill`（`--exec-delay 1` 下即成交日收盘）。流水是「人工核对用」的凭证，
                # 记错价会让对账人得出与实际不同的成本；成交本身一直用的是 `fill`（`shares = amount/fill`），
                # 故本次修正只改打印列，不改任何回测结果。
                ledger.append({"date": day, "security_code": code, "action": "买入",
                               "shares": f"{shares:.0f}", "price": f"{fill:.3f}",
                               "amount": f"{amount:.0f}", "pv_ratio": f"{ratio:.4f}",
                               "intrinsic_value": f"{value:.3f}",
                               "reason": "定投加仓" if lot.buys > 1 else "首次建仓"})
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
        # 融资棘轮（§13.2）：日终剩余现金先还融资，不留到下一笔买入。
        repay_debt(portfolio, margin_ratchet)
        # **无单票上限的实际后果必须可量**（§9.7.1 明文不设单票上限）：逐日记下最大单股权重
        # 与前三大合计，写进净值曲线。不记的话「集中度」只能靠事后从流水重建，而流水按构造
        # 缺部分减持（本次一并补上），重建值会系统性偏高。
        eq_now = portfolio.equity(marks)
        weights = sorted((lot.shares * marks[c] / eq_now
                          for c, lot in portfolio.lots.items() if c in marks and eq_now > 0),
                         reverse=True)
        equity_curve.append((day, eq_now, portfolio.cash, len(portfolio.lots),
                             portfolio.debt, portfolio.margin_ratio(marks),
                             weights[0] if weights else 0.0, sum(weights[:3])))

    # 收尾：按最后一日收盘价清算未平仓，使逐周期收益可比
    if days:
        last = days[-1]
        for code in list(portfolio.lots):
            price = prices.get(code, {}).get(last)
            if price:
                close_lot(portfolio, code, last, price, "回测截止清算")
    return {"equity": equity_curve, "closed": portfolio.closed,
            "buys": buy_count, "sells": sell_count, "turnover": turnover,
            "margin_events": margin_events, "min_margin_ratio": min_ratio,
            "min_margin_day": min_ratio_day, "interest_paid": portfolio.interest_paid,
            "final_debt": portfolio.debt}


# ------------------------------------------------------------------ 指标
def period_returns(curve: list[tuple[str, float, float, int]], key) -> list[tuple[str, float]]:
    buckets: dict[str, tuple[float, float]] = {}
    for day, equity, *_rest in curve:
        label = key(day)
        first, _ = buckets.get(label, (equity, equity))
        buckets[label] = (first, equity)
    return [(k, last / first - 1) for k, (first, last) in sorted(buckets.items())]


def max_drawdown(curve) -> tuple[float, str, str]:
    peak, worst, start, end, peak_day = -1.0, 0.0, "", "", ""
    for day, equity, *_r in curve:
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
        for _d, equity, *_r in seg:
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
    exposure = statistics.fmean([1 - c / e for _d, e, c, *_r in curve if e > 0])

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
            "年均换手": (result["turnover"] / years / statistics.fmean([e for _d, e, *_r in curve])
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
        writer.writerow(["date", "net_equity", "cash", "positions", "cash_ratio",
                         "debt", "margin_ratio", "top1_weight", "top3_weight"])
        for day, equity, cash, count, *rest in curve:
            debt = rest[0] if rest else 0.0
            ratio = rest[1] if len(rest) > 1 else float("inf")
            top1 = rest[2] if len(rest) > 2 else 0.0
            top3 = rest[3] if len(rest) > 3 else 0.0
            writer.writerow([day, f"{equity:.2f}", f"{cash:.2f}", count,
                             f"{cash / equity:.4f}" if equity else "",
                             f"{debt:.2f}", "" if ratio == float("inf") else f"{ratio:.4f}",
                             f"{top1:.4f}", f"{top3:.4f}"])


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
    mg = parser.add_argument_group("融资（杠杆）")
    mg.add_argument("--credit-ratio", type=float, default=0.0,
                    help="授信额度 ÷ 净资产。用户口径：净资产300万授权200万 → 0.667。0=不用杠杆")
    mg.add_argument("--credit-cap", type=float, default=10_000_000.0,
                    help="授信绝对上限（元），默认 1000 万")
    mg.add_argument("--margin-rate", type=float, default=0.035, help="融资年利率")
    mg.add_argument("--maintenance-ratio", type=float, default=1.30, help="平仓线（担保比例）")
    mg.add_argument("--recover-ratio", type=float, default=1.50,
                    help="强平后需恢复到的担保比例")
    mg.add_argument("--margin-ratchet", action="store_true",
                    help="融资棘轮：日终剩余现金先还融资，不留到下一笔买入")
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
    parser.add_argument("--liquidate-ma", type=int, default=0,
                        help="一键清仓的均线（0=不启用）：`P/V ≥ 减持线` 且连续 N 日跌破它即整仓卖出。"
                             "120=半年线、240=年线。与 --trend-exit-ma 的区别是它须同时满足 P/V 条件")
    parser.add_argument("--liquidate-days", type=int, default=3,
                        help="一键清仓要求的连续跌破天数")
    parser.add_argument("--sell-trend-ma", nargs="*", type=int, default=[],
                        help="减持的前置走势闸门：给 `5 20` 表示还须 收盘<MA5<MA20 才按一档减。"
                             "空=原行为（纯估值触发）。只闸 P/V 减持，不闸出名单清仓与换仓")
    parser.add_argument("--exec-delay", type=int, choices=(0, 1), default=0,
                        help="0=T 日收盘算信号当日成交（现行）；1=T 日收盘算信号、T+1 日成交")
    parser.add_argument("--exec-price", choices=("close", "open"), default="close",
                        help="--exec-delay 1 时的成交价取 T+1 的开盘还是收盘")
    parser.add_argument("--trend-tol", type=float, nargs="+", default=[0.0],
                        help="走势条件容差 t：判据放宽为 收盘 > MA20×(1−t) 且 MA20 > MA60×(1−t)。"
                             "0.005 即 0.5%%。可给多个做敏感度")
    parser.add_argument("--trend-ma", nargs="+", type=int, default=[20, 60],
                        help="走势触发的均线，如 `20 60` 表示 收盘>MA20>MA60；`5 20` 表示 收盘>MA5>MA20；单个值表示只要求站上该均线")
    parser.add_argument("--sell-line", type=float, default=0.0,
                        help="减持线（P/V），缺省 1+w；设为 1.30 即涨到 30%% 溢价才减持")
    parser.add_argument("--trend-tranche", action="store_true",
                        help="走势组改为分批建仓：只要当日仍满足均线与估值条件就按 x%% 继续买入")
    parser.add_argument("--research-gate",
                        choices=("off", "rating", "nodown", "target", "eps", "both"),
                        default="off", help="研报预期方向门槛，见 ResearchGate 文档串")
    parser.add_argument("--research-window", type=int, default=180, help="研报回看天数（对比窗口同长）")
    parser.add_argument("--research-tol", type=float, default=0.0,
                        help="容忍的下滑幅度：rating 为评级均值降幅，eps 为预测降幅比例")
    parser.add_argument("--research-missing", choices=("pass", "block"), default="pass",
                        help="无研报覆盖时放行还是拦截。**block 会把它变成规模过滤器**")
    parser.add_argument("--lot-ratio-cooldown", action="store_true",
                        help="§9.7.3 比例冷却：一手价值是一档的 x 倍时，成交一手后跳过 round(x)−1 次合格机会（买卖共用）")
    parser.add_argument("--min-lot-cooldown", type=int, default=0, metavar="D",
                        help="高价股一档买不起一手时，改为每 D 个自然日买一手；0 表示跳过不买")
    parser.add_argument("--trade-log", type=Path, help="导出逐笔成交流水（人工核对用）")
    parser.add_argument("--rebuy", choices=("off", "lump", "gradual"), default="off",
                        help="割肉后的买回口径：lump=重新合格当日一次性买回相同股数；gradual=交回常规定投")
    parser.add_argument("--lot-size", type=int, default=0, metavar="N",
                        help="最小交易单位（A股填 100）。打开后买入按手向下取整、买不足一手则跳过")
    parser.add_argument("--swap-partial", action="store_true",
                        help="换仓由整仓卖出改为按定投同速减一档（仅在只差钱、槽位未满时）")
    parser.add_argument("--cluster-swap", action="store_true",
                        help="簇内升级模式：相关性用作「替换谁」的判据而非排除过滤器，持仓数不设上限")
    parser.add_argument("--cluster-delta", type=float, default=0.85,
                        help="判定「同簇」的相关性阈值；超过它才视为可互相替换")
    parser.add_argument("--cluster-min-upside", type=float, default=20.0, metavar="PCT",
                        help="备选的最低空间（百分数），空间=V/P−1")
    parser.add_argument("--swap-bypass-corr", action="store_true",
                        help="已为之腾过位的换仓目标豁免相关性检查——卖都卖了就该买到它")
    parser.add_argument("--research-permute", type=int, default=0, metavar="N",
                        help="安慰剂：研报序列按代码序错位 N 位，保留拦截强度、抹掉个股信息")
    parser.add_argument("--label-suffix", default="")
    args = parser.parse_args()

    print(f"载入…（逐日估值状态、行情、除权除息、均线）")
    universe = load_universe(args.universe_file) if args.universe_file else None
    states = load_states(args.daily_states,
                         {c for _d, m in universe for c in m} if universe else None)
    prices = load_prices({r[0] for rows in states.values() for r in rows})
    opens = (load_opens({r[0] for rows in states.values() for r in rows})
             if args.exec_delay and args.exec_price == "open" else None)
    actions = load_actions()
    names, benchmark, risk_free = load_names(), load_benchmark(), load_risk_free()
    # 均线窗口按**本次实际用到的**收集，缺哪条算哪条。此前固定 (5,10,20,60,120,240)，
    # 传入未预计算的窗口（如 `--trend-ma 10 30`）会使条件恒假、**一笔交易都不产生却不报错**
    # ——典型的静默失效（§15.2 第 3 条），2026-08-09 实测撞到后修正。
    windows = sorted({5, 10, 20, 60, 120, 240} | set(args.trend_ma) | set(args.hold_strong_ma)
                     | set(args.sell_trend_ma) | ({args.liquidate_ma} if args.liquidate_ma else set())
                     | {args.dev_ma, args.stop_ma} | ({args.trend_exit_ma} if args.trend_exit_ma else set()))
    mas = {code: moving_averages(series, tuple(w for w in windows if w > 0))
           for code, series in prices.items()}
    lows = {code: new_low_flags(series) for code, series in prices.items()}
    day_lists = {code: sorted(series) for code, series in prices.items()}
    day_pos = {code: {d: i for i, d in enumerate(ds)} for code, ds in day_lists.items()}
    corr = Correlations(daily_returns(prices, actions), args.corr_window) if args.max_corr else None
    research = None
    if args.research_gate != "off":
        ratings, downgrades, forecasts, targets = load_research(set(prices), actions=actions)
        research = ResearchGate(ratings, downgrades, forecasts, targets,
                                window=args.research_window, tol=args.research_tol,
                                missing=args.research_missing, permute=args.research_permute)
        spans = [d for series in ratings.values() for d, _ in series[:1]]
        print(f"  **研报门槛 {args.research_gate}**：有评级 {len(ratings):,} 只｜有下调记录 {len(downgrades):,} 只｜"
              f"有目标价 {len(targets):,} 只｜有预测 {len(forecasts):,} 只｜"
              f"最早评级 {min(spans) if spans else '缺'}｜"
              f"窗口 {args.research_window}d｜容忍 {args.research_tol:g}｜无覆盖={args.research_missing}")
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
          for trend_tol in args.trend_tol:
            label = (f"{strategy}_x{x:g}_w{width:g}"
                     + (f"_tol{trend_tol:g}" if trend_tol else "")
                     + (f"_x{args.exec_delay}{args.exec_price[0]}" if args.exec_delay else "")
                     + (f"_sma{'-'.join(map(str, args.sell_trend_ma))}" if args.sell_trend_ma else "")
                     + (f"_liq{args.liquidate_ma}d{args.liquidate_days}" if args.liquidate_ma else "")
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
                     + ("_sp" if args.swap_partial else "")
                     + (f"_lot{args.lot_size}" if args.lot_size else "")
                     + (f"_ml{args.min_lot_cooldown}" if args.min_lot_cooldown else "")
                     + ("_lrc" if args.lot_ratio_cooldown else "")
                     + (f"_rb{args.rebuy}" if args.rebuy != "off" else "")
                     + (f"_cl{args.cluster_delta:g}u{args.cluster_min_upside:g}" if args.cluster_swap else "")
                     + (f"_rg{args.research_gate}{args.research_window}"
                        f"{'B' if args.research_missing == 'block' else ''}"
                        if args.research_gate != "off" else "")
                     + args.label_suffix)
            if research is not None:
                research.blocked.clear()
            run_stats = collections.Counter()
            ledger = [] if args.trade_log else None
            result = run(strategy, x / 100.0, states, prices, actions, mas,
                         args.since, args.until, args.capital, width=width, tiers=tiers,
                         credit_ratio=args.credit_ratio, credit_cap=args.credit_cap,
                         margin_rate=args.margin_rate,
                         maintenance=args.maintenance_ratio, recover_to=args.recover_ratio,
                         margin_ratchet=args.margin_ratchet,
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
                         trend_ma=tuple(args.trend_ma), trend_tol=trend_tol,
                         exec_delay=args.exec_delay, exec_price=args.exec_price, opens=opens,
                         sell_trend_ma=tuple(args.sell_trend_ma),
                         liquidate_ma=args.liquidate_ma, liquidate_days=args.liquidate_days,
                         sell_line_override=args.sell_line or None,
                         trend_exit_ma=args.trend_exit_ma,
                         rank_by_upside=args.rank_by_upside, entry_mode=args.entry_mode,
                         dev_ma=args.dev_ma, dev_buy_max=args.dev_buy_max,
                         dev_sell_min=args.dev_sell_min, hold_strong=args.hold_strong,
                         hold_strong_ma=tuple(args.hold_strong_ma), rank_mode=args.rank_mode,
                         quantile_window=args.quantile_window,
                         quantile_min_obs=args.quantile_min_obs,
                         research_gate=args.research_gate, research=research,
                         swap_bypass_corr=args.swap_bypass_corr, stats=run_stats,
                         cluster_swap=args.cluster_swap, cluster_delta=args.cluster_delta,
                         cluster_min_upside=args.cluster_min_upside / 100.0,
                         swap_partial=args.swap_partial, lot_size=args.lot_size, rebuy=args.rebuy,
                         ledger=ledger, min_lot_cooldown=args.min_lot_cooldown,
                         lot_ratio_cooldown=args.lot_ratio_cooldown)
            if not result["equity"]:
                print(f"  {label}: 无交易日")
                continue
            write_trades(args.out_dir / f"{label}_trades.csv", result["closed"], names)
            write_equity(args.out_dir / f"{label}_equity.csv", result["equity"])
            write_periods(args.out_dir / f"{label}_periods.csv", result["equity"])
            if ledger:
                with args.trade_log.open("w", newline="", encoding="utf-8") as handle:
                    w = csv.DictWriter(handle, fieldnames=list(ledger[0]) + ["security_name"])
                    w.writeheader()
                    for row in ledger:
                        w.writerow({**row, "security_name": names.get(row["security_code"], "")})
                print(f"    成交流水 {len(ledger):,} 笔 → {args.trade_log}")
            summary = summarize(label, result, args.capital, benchmark, risk_free)
            rows.append(summary)
            print(f"  {label}: 期末 {summary['期末资产']/1e4:,.1f} 万｜年化 {summary['年化']:.2%}"
                  f"｜最大回撤 {summary['最大回撤']:.1%}｜周期 {summary['周期数']}")
            if run_stats:
                print("    " + "｜".join(f"{k} {v:,}" for k, v in run_stats.most_common()))
            if research is not None and research.blocked:
                print("    研报门槛拦下（候选×日次）："
                      + "｜".join(f"{k} {v:,}" for k, v in research.blocked.most_common()))

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
