#!/usr/bin/env python3
"""幸存者偏差的两项量化（用户 2026-08-08 提出的质疑）。

用户原述：「我现在的回测都是基于现在还好好活着、而且经营得不错的公司进行的，但实际上
如果在 2010 年选值得关注的公司，很可能会有很多其他公司，然后这些公司在后续几年被淘汰了、
不在现在的名单里面，这就导致了这部分亏损没有完全考虑进来。」**这个质疑成立**，本脚本把它
的量级测出来。

两项分析
--------
**① 沪深261 指数**：拿当前池的 261 只，不做任何选股、按市值加权（另出等权版），
   与沪深300 对比。**它回答的是「策略的超额里有多少只是「持有今天这份名单」本身」**
   ——若指数化持有就已大幅跑赢沪深300，那么 §12.9 的超额主要来自名单而非选股逻辑。

   股本无现成字段，由 **`净利润 ÷ 每股收益`** 逐期推出（实测茅台 12.54 亿 vs 公开 12.56 亿、
   紫金 265.52 vs 265.8、美的 75.77 vs 76.6，误差 <1%，来自 EPS 的四舍五入）。
   **这是逐期的点位股本，不是今天的股本回填**，故送转与增发都自动含在内。

**② 时点重建的「值得关注」名单**：全市场逐季财务覆盖 1996 年至今、**含此后已退市的公司**
   （§12.4.2 已确认），故可以在每个历史时点**只用当时已披露的数据**跑一遍质量筛选，
   得到「当年会入选的名单」，再看其中有多少活到了今天、有多少进了今天的 261 只池。
   **两者之差就是幸存者偏差的直接度量。**

   筛选口径是 §5 质量分层的**定量代理**（§5 真正的护城河判断无法回放），刻意从简：
   连续 N 年年报 ROE ≥ 阈值、且净利润为正、且有足够年报历史。

用法::

    python3 scripts/analyze_survivorship_bias.py
    python3 scripts/analyze_survivorship_bias.py --roe 0.15 --years 5
"""
from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
OHLCV = ROOT / "data/raw/ohlcv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
BENCH = ROOT / "data/raw/ohlcv/INDEX_000300.csv"


def _num(v):
    try:
        return float((v or "").strip())
    except ValueError:
        return None


def load_annuals():
    """{代码: {财年: 行}}，只取年报。"""
    out = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as h:
            for r in csv.DictReader(h):
                if (r.get("notice_date") or "").strip():
                    out[r["security_code"]][r["report_date"][:4]] = r
    return out


def load_prices(codes):
    out = {}
    for code in codes:
        p = OHLCV / f"{code}.csv"
        if not p.exists():
            continue
        with p.open(newline="", encoding="utf-8") as h:
            out[code] = {r["date"]: float(r["close"]) for r in csv.DictReader(h)
                         if _num(r.get("close"))}
    return out


def build_index(codes, annuals, prices, weighting="cap"):
    """按市值或等权构造指数（基期 1000）。逐日再平衡，等价于持有全部成分。"""
    shares = {}
    for code in codes:
        for year, row in annuals.get(code, {}).items():
            profit, eps = _num(row.get("parent_netprofit")), _num(row.get("basic_eps"))
            if profit and eps and eps != 0 and profit / eps > 0:
                shares.setdefault(code, {})[row["notice_date"]] = profit / eps

    days = sorted({d for s in prices.values() for d in s})
    level, out, prev = 1000.0, [], None
    for day in days:
        live = [c for c in codes if c in prices and day in prices[c]]
        if len(live) < 5:
            continue
        if prev is not None:
            rets, weights = [], []
            for c in live:
                if c not in prev or prev[c][0] not in prices[c]:
                    continue
                p0 = prices[c][prev[c][0]]
                if p0 <= 0:
                    continue
                rets.append(prices[c][day] / p0 - 1)
                weights.append(prev[c][1] if weighting == "cap" else 1.0)
            if rets and sum(weights) > 0:
                level *= 1 + sum(r * w for r, w in zip(rets, weights)) / sum(weights)
                out.append((day, level))
        prev = {}
        for c in live:
            hist = shares.get(c, {})
            usable = [v for d, v in hist.items() if d <= day]
            cap = prices[c][day] * (usable[-1] if usable else 1.0)
            prev[c] = (day, cap)
    return out


def cagr(series):
    if len(series) < 2:
        return float("nan")
    years = len(series) / 244
    return (series[-1][1] / series[0][1]) ** (1 / years) - 1


def max_dd(series):
    peak, worst = -1.0, 0.0
    for _d, v in series:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, 1 - v / peak)
    return worst


def screen(annuals, as_of_year: int, roe_min: float, years: int):
    """时点筛选：截至 `as_of_year` 末，连续 `years` 个财年 ROE ≥ 阈值且净利为正。

    **只用当时已披露的年报**——每个财年的行都带 `notice_date`，此处按财年取，
    因 `as_of_year` 的年报要到次年才披露，故实际以 `as_of_year` 为最后一个完整财年、
    在次年 4-5 月才可用，下游据此对齐。
    """
    passed = []
    for code, rows in annuals.items():
        window = [str(y) for y in range(as_of_year - years + 1, as_of_year + 1)]
        vals = []
        for y in window:
            r = rows.get(y)
            if r is None:
                break
            roe, profit = _num(r.get("weightavg_roe")), _num(r.get("parent_netprofit"))
            if roe is None or profit is None or profit <= 0 or (roe == 0 and profit != 0):
                break
            vals.append(roe / 100.0)
        if len(vals) == len(window) and all(v >= roe_min for v in vals):
            passed.append(code)
    return passed


def main() -> int:
    ap = argparse.ArgumentParser(description="幸存者偏差量化")
    ap.add_argument("--roe", type=float, default=0.15)
    ap.add_argument("--years", type=int, default=5)
    args = ap.parse_args()

    tiers = {r["security_code"]: r["quality_tier"]
             for r in csv.DictReader(TIERS.open(encoding="utf-8"))}
    pool = sorted(tiers)
    annuals = load_annuals()
    prices = load_prices(pool)

    print(f"=== ① 沪深261 指数（当前池 {len(pool)} 只，不做任何选股） ===")
    bench = [(r["date"], float(r["close"])) for r in csv.DictReader(BENCH.open(encoding="utf-8"))
             if _num(r.get("close"))]
    for weighting, name in (("cap", "市值加权"), ("equal", "等权")):
        idx = build_index(pool, annuals, prices, weighting)
        idx = [x for x in idx if x[0] >= "2005-01-04"]
        if not idx:
            continue
        b = [x for x in bench if idx[0][0] <= x[0] <= idx[-1][0]]
        print(f"  沪深261·{name}：{idx[0][0]}~{idx[-1][0]}｜年化 **{cagr(idx):.2%}**｜最大回撤 {max_dd(idx):.1%}")
        if b:
            print(f"    同期沪深300：年化 {cagr(b):.2%}｜最大回撤 {max_dd(b):.1%}"
                  f"  → **超额 {cagr(idx) - cagr(b):+.2%}**")

    print(f"\n=== ② 时点重建「值得关注」名单（连续 {args.years} 年 ROE ≥ {args.roe:.0%} 且净利为正） ===")
    latest = max(y for rows in annuals.values() for y in rows) if annuals else "2025"
    print(f'{"筛选年":<8}{"当年入选":>9}{"活到今天":>10}{"存活率":>9}{"在今天的池里":>13}{"入池率":>9}')
    print("-" * 62)
    rates = []
    for year in range(2005, 2021, 5):
        passed = screen(annuals, year, args.roe, args.years)
        if not passed:
            continue
        alive = [c for c in passed if latest in annuals.get(c, {})]
        inpool = [c for c in passed if c in tiers]
        rates.append((year, len(passed), len(alive), len(inpool)))
        print(f'{year:<8}{len(passed):>9}{len(alive):>10}{len(alive)/len(passed):>9.1%}'
              f'{len(inpool):>13}{len(inpool)/len(passed):>9.1%}')
    if rates:
        print(f"\n**读法**：「入池率」= 当年按同一套质量标准选出来的公司里，有多大比例进了今天的 261 只。")
        print(f"  它的补集就是被回测**完全忽略**的那部分——它们当年同样会被选中，"
              f"此后或退市、或质量下滑而被剔除。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
