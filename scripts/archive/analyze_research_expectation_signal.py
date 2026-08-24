#!/usr/bin/env python3
"""研报预期方向的**前瞻收益检验**（OI-034 第 8 步配套，用户 2026-08-09）。

为什么先做这个再跑回测
----------------------
「只买近期研报预期在增长或几乎不变的公司」要成立，前提是**预期方向本身能预测收益**。
这一步单独量它：把每个月末的股票按预期方向分组，看各组此后 6 个月的收益差。
若各组无差异，则无论门槛怎么调参、回测跑出什么数，都是噪声——**先证信号，再证规则**。

口径
----
* 信号在月末计算，只用**该日之前**已发布的研报（`_slice` 两端开区间）。
* 目标价按送转折算（见 `backtest_valuation_strategy.load_research`）。
* 前瞻收益用**除权除息还原**的价格：`(P_end·∏(1+送转) + 累计现金分红) / P_start − 1`，
  不还原会把每一次 10 转 10 记成 −50%。
* 只统计当年在时点股票库内的公司——门槛是加在**候选池之上**的，不该拿池外股票评估。

用法::

    python3 scripts/analyze_research_expectation_signal.py
    python3 scripts/analyze_research_expectation_signal.py --horizon 120 --window 180
"""
from __future__ import annotations

import argparse
import bisect
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_valuation_strategy import (ResearchGate, load_actions, load_prices,  # noqa: E402
                                         load_research, load_universe)

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "data/archive/pit-judgment-2026-08/universe_panel_yearly.csv"


def forward_return(days: list[str], series: dict[str, float], events, start: str, horizon: int):
    """`horizon` 个交易日后的复权收益。缺价或不足期返回 None。"""
    i = bisect.bisect_left(days, start)
    if i >= len(days) or i + horizon >= len(days):
        return None
    a, b = days[i], days[i + horizon]
    p0, p1 = series.get(a), series.get(b)
    if not p0 or not p1 or p0 <= 0:
        return None
    factor, cash = 1.0, 0.0
    for day in days[i + 1:i + horizon + 1]:
        event = (events or {}).get(day)
        if event:
            cash += event[0] * factor
            factor *= (1.0 + event[1])
    return (p1 * factor + cash) / p0 - 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description="研报预期方向的前瞻收益检验")
    ap.add_argument("--window", type=int, default=180, help="研报回看天数（对比窗口同长）")
    ap.add_argument("--horizon", type=int, default=120, help="前瞻交易日数，120≈半年")
    ap.add_argument("--cut", type=float, default=0.05, help="上修/下修的判定阈值")
    ap.add_argument("--universe-file", type=Path, default=UNIVERSE)
    args = ap.parse_args()

    universe = load_universe(args.universe_file)
    codes = {c for _d, members in universe for c in members}
    actions = load_actions()
    prices = load_prices(codes)
    ratings, downgrades, forecasts, targets = load_research(codes, actions=actions)
    gate = ResearchGate(ratings, downgrades, forecasts, targets, window=args.window)
    day_lists = {code: sorted(series) for code, series in prices.items()}
    all_days = sorted({d for days in day_lists.values() for d in days})
    month_ends = [d for i, d in enumerate(all_days)
                  if i + 1 == len(all_days) or all_days[i + 1][:7] != d[:7]]
    month_ends = [d for d in month_ends if d >= "2018-01-01"]
    print(f"股票库并集 {len(codes):,} 只｜行情 {len(prices):,} 只｜"
          f"月末观测点 {len(month_ends)}（{month_ends[0]} ~ {month_ends[-1]}）｜"
          f"窗口 {args.window}d｜前瞻 {args.horizon} 交易日")

    buckets: dict[str, list[float]] = defaultdict(list)
    by_year: dict[tuple[str, str], list[float]] = defaultdict(list)
    index, members = 0, set()
    for day in month_ends:
        while index < len(universe) and universe[index][0] <= day:
            members = universe[index][1]
            index += 1
        mid, start = gate._shift(day, args.window), gate._shift(day, 2 * args.window)
        for code in members:
            series = prices.get(code)
            if not series:
                continue
            ahead = forward_return(day_lists[code], series, actions.get(code), day, args.horizon)
            if ahead is None:
                continue
            tgt = targets.get(code)
            recent = gate._slice(tgt, mid, day) if tgt else []
            prior = gate._slice(tgt, start, mid) if tgt else []
            if recent and prior and statistics.median(prior) > 0:
                change = statistics.median(recent) / statistics.median(prior) - 1
                label = ("目标价上修" if change > args.cut else
                         "目标价下修" if change < -args.cut else "目标价持平")
            elif recent or prior:
                label = "目标价单边"
            else:
                label = "无目标价"
            buckets[label].append(ahead)
            by_year[(day[:4], label)].append(ahead)
            down = downgrades.get(code)
            buckets["评级被下调" if down and gate._slice(down, mid, day) else "无评级下调"].append(ahead)

    order = ["目标价上修", "目标价持平", "目标价下修", "目标价单边", "无目标价",
             "无评级下调", "评级被下调"]
    print(f'\n{"分组":<12}{"观测":>9}{"平均前瞻收益":>14}{"中位":>10}{"胜率":>9}')
    print("-" * 56)
    for label in order:
        values = buckets.get(label)
        if not values:
            continue
        print(f"{label:<12}{len(values):>9,}{statistics.fmean(values):>13.2%}"
              f"{statistics.median(values):>10.2%}"
              f"{sum(1 for v in values if v > 0) / len(values):>9.1%}")

    print(f'\n逐年（平均前瞻收益）｜{"年":<6}' + "".join(f"{k:>12}" for k in
          ("目标价上修", "目标价持平", "目标价下修", "无目标价")))
    for year in sorted({y for y, _ in by_year}):
        cells = []
        for label in ("目标价上修", "目标价持平", "目标价下修", "无目标价"):
            values = by_year.get((year, label))
            cells.append(f"{statistics.fmean(values):>11.1%}" if values else f'{"-":>11}')
        print(f'{"":<18}{year:<6}' + " ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
