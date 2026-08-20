#!/usr/bin/env python3
"""单票终值参数实验台（OI-070 / OI-076 同源问题，2026-08-20 用户指令「从特殊到一般」）。

问题：所有公司共用一套终值假设（`N=10` 年线性 fade、`ROIC_T = WACC + 2pp`），护城河强弱不进入价值。
本工具把**同一只股票在不同终值参数下的逐日 `P/V`** 并排放在一起，回答三个可核验的问题：

1. **暴露**：在现行三条线（买 ≤ 0.9407、减持 ≥ 2.5236）下，各变体每年有多少天落在可买／可持有／减持区；
2. **关键时点**：公认的底部（2013-12 塑化剂、2018-10、2024-09）与顶部（2007-10、2021-02）各读多少；
3. **公允校准**：`P/V` 与其后 3 年／5 年**含分红再投**总回报的关系——`P/V ≈ 1` 是否对应约 10%/年
   （模型 r 的语义就是要求回报率），以及把 5 年前向年化拉到 10% 的 `P/V` 水平在哪里。

输入是 `build_historical_valuation_bands.py --out-daily` 的逐日状态文件（每个变体一份）。
只读不写、不碰生产文件；结论记回测日志。

用法::

    python3 scripts/experimental/moat_param_lab.py --code 600519 \
        --states BASE=/path/base_daily.csv E6=/path/E6_daily.csv N20=/path/N20_daily.csv \
        --key-dates 2007-10-16 2013-12-30 2018-10-30 2021-02-10 2024-09-18
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_historical_valuation_bands as bhv  # noqa: E402

BUY_LINE, SELL_LINE = 0.9407, 2.5236          # §9.3.1 现行值，只作实验对照
BUCKETS = ((0, 0.8), (0.8, BUY_LINE), (BUY_LINE, 1.2), (1.2, 1.6), (1.6, 2.0),
           (2.0, SELL_LINE), (SELL_LINE, 4.0), (4.0, 99.0))


def total_return_index(prices: list[tuple[str, float]], actions: list[dict]) -> dict[str, float]:
    """持 1 股、现金分红按除权日收盘再投、送转按比例加股 → 逐日总回报指数（与价同基）。"""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for a in actions:
        if a.get("ex_dividend_date"):
            by_day[a["ex_dividend_date"]].append(a)
    shares, out = 1.0, {}
    for day, close in prices:
        for a in by_day.get(day, ()):
            cash = bhv._num(a.get("cash_per_share")) or 0.0
            ratio = bhv._num(a.get("share_ratio")) or 0.0
            paid = shares * cash
            shares *= (1 + ratio)
            if close > 0 and paid > 0:
                shares += paid / close
        out[day] = shares * close
    return out


def forward_annualized(tr: dict[str, float], days: list[str], start: str, years: int) -> float | None:
    """自 `start` 起 `years` 年的年化总回报；终点取 ≤ 目标日的最后一个交易日，不足整段返回 None。"""
    d0 = date.fromisoformat(start)
    try:
        target = d0.replace(year=d0.year + years).isoformat()
    except ValueError:
        target = d0.replace(year=d0.year + years, day=28).isoformat()
    i = bisect.bisect_right(days, target) - 1
    if i < 0 or days[i] <= start:
        return None
    end = days[i]
    if (date.fromisoformat(end) - d0).days < years * 365 - 10:
        return None
    return (tr[end] / tr[start]) ** (1 / years) - 1


def load_states(path: Path, code: str) -> dict[str, tuple[float, float]]:
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["security_code"].zfill(6) != code or not r.get("valuation_ratio"):
                continue
            out[r["date"]] = (float(r["valuation_ratio"]), float(r["intrinsic_value"]))
    return out


def spearman(xs, ys):
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else float("nan")


def loglinear_fair_pv(pairs: list[tuple[float, float]], target: float) -> float | None:
    """拟合 `fwd = a + b·ln(P/V)`，解 `fwd = target` 的 P/V。b ≥ 0（便宜不对应更高回报）时返回 None。"""
    if len(pairs) < 24:
        return None
    xs = [math.log(p) for p, _ in pairs]
    ys = [f for _, f in pairs]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    if b >= 0:
        return None
    fair = math.exp((target - a) / b)
    # 斜率趋零时解会飞到观测范围之外——那不是「公允点在 100」，是「P/V 与前向回报没有关系」。
    # 夹到观测范围的 [0.5×最小, 2×最大] 之外即视为无解。
    lo, hi = min(p for p, _ in pairs), max(p for p, _ in pairs)
    if not (0.5 * lo <= fair <= 2 * hi):
        return None
    return fair


def month_ends(days: list[str]) -> list[str]:
    out, prev = [], None
    for d in days:
        if prev is not None and prev[:7] != d[:7]:
            out.append(prev)
        prev = d
    if prev:
        out.append(prev)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--states", nargs="+", required=True, help="标签=逐日状态文件")
    ap.add_argument("--key-dates", nargs="*", default=[])
    ap.add_argument("--since", default="2004-01-01", help="暴露与校准统计的起点")
    ap.add_argument("--hurdle", type=float, default=0.10)
    a = ap.parse_args()
    code = a.code.zfill(6)

    prices = bhv.load_ohlcv(code)
    actions = bhv.load_actions().get(code, [])
    tr = total_return_index(prices, actions)
    days = [d for d, _ in prices]
    close = dict(prices)

    variants = []
    for item in a.states:
        tag, path = item.split("=", 1)
        variants.append((tag, load_states(Path(path), code)))

    # ---------- 1. 关键时点 ----------
    if a.key_dates:
        print(f"\n### 关键时点 `P/V`（{code}；价=该日或其后首个交易日收盘）\n")
        print("| 日期 | 收盘 | " + " | ".join(t for t, _ in variants) + " |")
        print("| --- | ---: | " + " | ".join("---:" for _ in variants) + " |")
        for kd in a.key_dates:
            i = bisect.bisect_left(days, kd)
            if i >= len(days):
                continue
            d = days[i]
            cells = []
            for _tag, st in variants:
                v = st.get(d)
                cells.append(f"{v[0]:.2f}" if v else "—")
            print(f"| {d} | {close[d]:.2f} | " + " | ".join(cells) + " |")

    # ---------- 2. 逐年暴露 ----------
    print(f"\n### 逐年 `P/V` 中位 ／ 可买天数（≤{BUY_LINE}）／ 减持区天数（≥{SELL_LINE}）\n")
    header = "| 年 | 天 | " + " | ".join(f"{t} 中位/买/减" for t, _ in variants) + " |"
    print(header)
    print("| --- | ---: | " + " | ".join("---" for _ in variants) + " |")
    years = sorted({d[:4] for d in days if d >= a.since})
    totals = {t: [0, 0, 0] for t, _ in variants}
    for y in years:
        ds = [d for d in days if d[:4] == y]
        cells = []
        for tag, st in variants:
            pv = [st[d][0] for d in ds if d in st]
            if not pv:
                cells.append("—")
                continue
            buy = sum(1 for x in pv if x <= BUY_LINE)
            sell = sum(1 for x in pv if x >= SELL_LINE)
            totals[tag][0] += len(pv)
            totals[tag][1] += buy
            totals[tag][2] += sell
            cells.append(f"{statistics.median(pv):.2f} / {buy} / {sell}")
        print(f"| {y} | {len(ds)} | " + " | ".join(cells) + " |")
    print("\n暴露合计（自 " + a.since + "）：" + "｜".join(
        f"{t} 可买 {b}/{n} ({b / n:.0%})·减持区 {s}/{n} ({s / n:.0%})"
        for t, (n, b, s) in totals.items() if n))

    # ---------- 3. 公允校准 ----------
    print(f"\n### 公允校准：月末 `P/V` → 其后 3 年／5 年含分红再投年化总回报（自 {a.since}）\n")
    print("| 变体 | n(5y) | Spearman(5y) | 拟合 fwd5y={:.0%} 的 P/V | 拟合 fwd3y={:.0%} 的 P/V | ".format(a.hurdle, a.hurdle)
          + " | ".join(f"[{lo:g},{hi:g})" for lo, hi in BUCKETS) + " |")
    print("| --- | ---: | ---: | ---: | ---: | " + " | ".join("---:" for _ in BUCKETS) + " |")
    me = [d for d in month_ends(days) if d >= a.since]
    for tag, st in variants:
        p5, p3 = [], []
        for d in me:
            if d not in st:
                continue
            f5 = forward_annualized(tr, days, d, 5)
            f3 = forward_annualized(tr, days, d, 3)
            if f5 is not None:
                p5.append((st[d][0], f5))
            if f3 is not None:
                p3.append((st[d][0], f3))
        rho = spearman([p for p, _ in p5], [f for _, f in p5]) if len(p5) > 5 else float("nan")
        fair5 = loglinear_fair_pv(p5, a.hurdle)
        fair3 = loglinear_fair_pv(p3, a.hurdle)
        cells = []
        for lo, hi in BUCKETS:
            sel = [f for p, f in p5 if lo <= p < hi]
            cells.append(f"{statistics.median(sel):+.0%} (n={len(sel)})" if sel else "—")
        print(f"| {tag} | {len(p5)} | {rho:+.2f} | "
              f"{fair5 if fair5 is None else round(fair5, 2)} | {fair3 if fair3 is None else round(fair3, 2)} | "
              + " | ".join(cells) + " |")
    print("\n读法：各桶给该桶内月末起算的 5 年年化中位；「拟合 P/V」是对数线性回归上 5 年年化恰等于要求回报的"
          " `P/V`——模型若公允，该值应≈1。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
