#!/usr/bin/env python3
"""幸存者/选样偏差的直接度量：2010 年时点名单里「进池」与「未进池」两组的此后收益。

为什么这样测
------------
§12.9.9 已经确认：**退市不是渠道**（该质量门槛下存活率 99.7%~100%），真正的渠道是
**「质量漂移 + 名单策展」**——2010 年按同一套定量标准会选出 116 家，只有 30 家进了今天的
261 只池，另外 86 家至今仍上市却从未被回测持有。

**偏差的真实幅度 = 这两组此后收益之差。** 若「未进池」组的收益显著低于「进池」组，
那么以今天的池为可选池的回测就系统性地只挑了赢家；若两组接近，则偏差有限。

口径
----
* 起点取 **2011-05-02**：2010 年报要到次年 4 月底才披露完，这是「当时真能知道」的最早时点。
* 收益按**总回报**算：不复权价 × 累计送转 + 累计现金红利（与 §12.4.1 的口径一致）。
* 两组都**等权持有到底**，不做任何调仓——测的是名单本身的质量差，不是策略。
* 停牌/退市：以最后一个有成交的交易日收盘价结算。

用法::

    python3 scripts/measure_pool_selection_bias.py
    python3 scripts/measure_pool_selection_bias.py --start 2011-05-02 --end 2026-08-07
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
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"
BENCH = ROOT / "data/raw/ohlcv/INDEX_000300.csv"


def _num(v):
    try:
        return float((v or "").strip())
    except (ValueError, TypeError):
        return None


def is_a_share(code: str) -> bool:
    return code[:1] in ("0", "3", "6") and code[:2] not in ("43", "83", "87", "88", "92")


def screen(annuals, as_of_year: int, roe_min=0.15, years=5):
    out = []
    for code, rows in annuals.items():
        if not is_a_share(code):
            continue
        vals = []
        for y in [str(x) for x in range(as_of_year - years + 1, as_of_year + 1)]:
            r = rows.get(y)
            if r is None:
                break
            roe, profit = _num(r.get("weightavg_roe")), _num(r.get("parent_netprofit"))
            if roe is None or profit is None or profit <= 0 or (roe == 0 and profit != 0):
                break
            vals.append(roe / 100.0)
        if len(vals) == years and all(v >= roe_min for v in vals):
            out.append(code)
    return out


def total_return(code, start, end, actions):
    """区间总回报：不复权价 × 累计送转 + 累计现金红利（按持有 1 股起算）。"""
    path = OHLCV / f"{code}.csv"
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as h:
        px = {r["date"]: float(r["close"]) for r in csv.DictReader(h) if _num(r.get("close"))}
    days = sorted(d for d in px if start <= d <= end)
    if len(days) < 60:
        return None
    shares, cash = 1.0, 0.0
    for day, (cps, ratio) in sorted(actions.get(code, {}).items()):
        if start < day <= days[-1]:
            cash += shares * cps
            shares *= (1 + ratio)
    return (px[days[-1]] * shares + cash) / px[days[0]] - 1, days[0], days[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="池选样偏差的直接度量")
    ap.add_argument("--year", type=int, default=2010, help="时点筛选年")
    ap.add_argument("--start", default="2011-05-02", help="持有起点（年报披露完之后）")
    ap.add_argument("--end", default="2026-08-07")
    args = ap.parse_args()

    annuals = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as h:
            for r in csv.DictReader(h):
                if (r.get("notice_date") or "").strip():
                    annuals[r["security_code"]][r["report_date"][:4]] = r

    acts = defaultdict(dict)
    with ACTIONS.open(newline="", encoding="utf-8") as h:
        for r in csv.DictReader(h):
            d = (r.get("ex_dividend_date") or "").strip()
            if d:
                c0, r0 = acts[r["security_code"]].get(d, (0.0, 0.0))
                acts[r["security_code"]][d] = (c0 + (_num(r.get("cash_per_share")) or 0.0),
                                               (1 + r0) * (1 + (_num(r.get("share_ratio")) or 0.0)) - 1)

    pool = {r["security_code"] for r in csv.DictReader(TIERS.open(encoding="utf-8"))}
    names = {r["security_code"]: r["security_name"]
             for r in csv.DictReader(TIERS.open(encoding="utf-8"))}
    cohort = screen(annuals, args.year)

    groups = {"进池": [], "未进池": []}
    missing = []
    for code in cohort:
        res = total_return(code, args.start, args.end, acts)
        if res is None:
            missing.append(code)
            continue
        groups["进池" if code in pool else "未进池"].append((code, res[0]))

    print(f"=== {args.year} 年时点名单（连续 5 年 ROE≥15% 且盈利）此后表现 ===")
    print(f"持有区间 {args.start} ~ {args.end}｜等权持有到底、不调仓｜总回报口径（含送转与分红）")
    print(f"名单 {len(cohort)} 只｜可算 {sum(len(v) for v in groups.values())} 只"
          f"｜**无行情 {len(missing)} 只**" + (f"（{'、'.join(missing[:8])}…）" if missing else ""))
    print()
    print(f'{"分组":<10}{"只数":>6}{"等权总回报":>12}{"年化":>9}{"收益中位":>11}{"跑赢沪深300占比":>16}{"亏损占比":>10}')
    print("-" * 76)

    bench = None
    with BENCH.open(newline="", encoding="utf-8") as h:
        b = {r["date"]: float(r["close"]) for r in csv.DictReader(h) if _num(r.get("close"))}
    bd = sorted(d for d in b if args.start <= d <= args.end)
    if len(bd) > 2:
        bench = b[bd[-1]] / b[bd[0]] - 1
    years = (len(bd) / 244) if bd else 15.3

    for label, rows in groups.items():
        if not rows:
            continue
        rets = [x[1] for x in rows]
        eq = statistics.fmean(rets)
        ann = (1 + eq) ** (1 / years) - 1
        beat = sum(1 for r in rets if bench is not None and r > bench) / len(rets)
        loss = sum(1 for r in rets if r < 0) / len(rets)
        print(f'{label:<10}{len(rows):>6}{eq:>12.1%}{ann:>9.1%}{statistics.median(rets):>11.1%}'
              f'{beat:>16.0%}{loss:>10.0%}')
    if bench is not None:
        print(f'{"沪深300":<10}{"":>6}{bench:>12.1%}{(1+bench)**(1/years)-1:>9.1%}')

    a, b_ = groups["进池"], groups["未进池"]
    if a and b_:
        ea, eb = statistics.fmean([x[1] for x in a]), statistics.fmean([x[1] for x in b_])
        aa = (1 + ea) ** (1 / years) - 1
        ab = (1 + eb) ** (1 / years) - 1
        print(f"\n**选样偏差幅度 = 两组年化之差 = {aa - ab:+.2%}**"
              f"（进池 {aa:.2%} vs 未进池 {ab:.2%}）")
        print("  这就是「以今天的池为可选池」相对「以当年时点名单为可选池」多拿到的部分——"
              "\n  §12.9 的全部回测收益里，应扣掉约这个量级才是可复现的。")
        worst = sorted(b_, key=lambda x: x[1])[:5]
        print("\n  未进池组里表现最差的 5 只（回测从未持有过它们）：")
        for c, r in worst:
            print(f"    {c} {names.get(c,''):<10} 总回报 {r:>8.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
