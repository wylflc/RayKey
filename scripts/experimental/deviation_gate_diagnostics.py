"""偏离度闸门（`--entry-mode both --dev-buy-max K`）的三项诊断，`docs/Ashare_backtest_log.md` §12.40 的证据来源。

回答三个问题，全部在**买入合格集**上做——面板在册 ∩ `P/V ≤ 买入线` ∩ `收 > MA20 > MA60`：

1. **闸门到底挡掉多少**：`收/MA60` 的分位数，与各阈值 K 的挡掉占比。
   （用来判断某个 K 的回测读数是「真效应」还是「几十笔交易的路径扰动」。）
2. **偏离度含不含信息**：按 `收/MA60` 十分位看未来 20/60 日收益的**中位与均值**。
   两者背离是本节的关键——中位单调变差，均值没有梯度，因为左右尾同时变肥。
3. **止损是不是已经把它吃掉了**：同一批观测，比较「裸持 60 日」与「跌破建仓日 MA20 即止损」。

均线口径与回测逐位一致：`moving_averages` 直接跑在 `data/raw/ohlcv/*.csv` 的**未复权收盘**上
（见 `backtest_valuation_strategy.py` 的 `moving_averages`），此处照抄，不另立算法。
前向收益同样用未复权收盘，故除权除息会低估长窗口收益——**只看 20/60 日短窗，不要拿它算长期持有**。

用法：
    python3 scripts/experimental/deviation_gate_diagnostics.py <逐日估值状态.csv> <面板.csv> [买入线] [起点]
"""
import bisect
import collections
import csv
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DAILY = sys.argv[1]
PANEL = sys.argv[2]
BUY_LINE = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5853
SINCE = sys.argv[4] if len(sys.argv) > 4 else "2009-11-01"
DECILES = 10


def load_panel(path):
    """面板：code -> [(effective_from, effective_to)]，用于「当时是否真的在册」。"""
    spans = collections.defaultdict(list)
    for row in csv.DictReader(open(path, encoding="utf-8")):
        spans[row["security_code"]].append((row["effective_from"], row["effective_to"]))
    return spans


def load_prices(codes):
    """未复权收盘 + MA20/MA60，与回测同源。"""
    px, idx, mas = {}, {}, {}
    for code in codes:
        try:
            rows = sorted((r["date"], float(r["close"]))
                          for r in csv.DictReader(open(ROOT / "data/raw/ohlcv" / f"{code}.csv", encoding="utf-8"))
                          if r.get("close"))
        except (FileNotFoundError, ValueError):
            continue
        days = [d for d, _ in rows]
        vals = [v for _, v in rows]
        px[code], idx[code] = vals, {d: i for i, d in enumerate(days)}
        out = {}
        for window in (20, 60):
            total = 0.0
            for i, value in enumerate(vals):
                total += value
                if i >= window:
                    total -= vals[i - window]
                if i >= window - 1:
                    out.setdefault(days[i], {})[window] = total / window
        mas[code] = out
    return px, idx, mas


def collect(daily, spans, px, idx, mas):
    """买入合格集：每条记 (收/MA60, 裸持20日, 裸持60日, 止损后60日)。"""
    in_panel = lambda c, d: any(a <= d < b for a, b in spans[c])
    obs = []
    n_pv = 0
    for row in csv.DictReader(open(daily, encoding="utf-8")):
        code, day = row["security_code"], row["date"]
        if day < SINCE or code not in mas or not in_panel(code, day):
            continue
        try:
            ratio, close = float(row["valuation_ratio"]), float(row["close"])
        except (TypeError, ValueError):
            continue
        if ratio > BUY_LINE:
            continue
        n_pv += 1
        ma = mas[code].get(day)
        if not ma or 20 not in ma or 60 not in ma or not close > ma[20] > ma[60]:
            continue
        i = idx[code].get(day)
        if i is None:
            continue
        series = px[code]
        fwd20 = series[i + 20] / close - 1 if i + 20 < len(series) else None
        if i + 60 >= len(series):
            obs.append((close / ma[60], fwd20, None, None))
            continue
        fwd60 = series[i + 60] / close - 1
        stopped = fwd60
        for j in range(i + 1, i + 61):          # 建仓日 MA20 是静态止损价，加仓不重设
            if series[j] < ma[20]:
                stopped = series[j] / close - 1
                break
        obs.append((close / ma[60], fwd20, fwd60, stopped))
    return obs, n_pv


def main():
    spans = load_panel(PANEL)
    px, idx, mas = load_prices(spans)
    obs, n_pv = collect(DAILY, spans, px, idx, mas)
    obs.sort()
    n = len(obs)
    devs = [o[0] for o in obs]
    print(f"面板内 P/V ≤ {BUY_LINE} 的观测 {n_pv:,} 个；再过走势闸门后 **{n:,} 个**"
          f"（{n / n_pv * 100:.1f}%）——这就是买入合格集，{SINCE} 起\n")

    print("① 闸门作用面：收/MA60 分位", end="")
    for q in (5, 25, 50, 75, 90, 95, 99):
        print(f"  P{q}={devs[int(n * q / 100)]:.3f}", end="")
    print(f"  最大 {devs[-1]:.3f}\n")
    print(f"{'阈值 K':>8}{'保留':>10}{'挡掉':>10}{'挡掉占比':>11}")
    for k in (1.02, 1.05, 1.08, 1.10, 1.15, 1.20, 1.30, 1.50):
        keep = bisect.bisect_right(devs, k)
        print(f"{k:>8.2f}{keep:>10,}{n - keep:>10,}{(n - keep) / n * 100:>10.1f}%")

    print(f"\n② 偏离度含不含信息（中位 vs 均值——背离才是重点）")
    print(f"{'十分位':>7}{'收/MA60':>16}{'20日中位':>10}{'60日中位':>10}{'60日均值':>10}{'60日P90':>9}{'60日P10':>9}")
    for k in range(DECILES):
        g = obs[n * k // DECILES:n * (k + 1) // DECILES]
        r20 = [x[1] for x in g if x[1] is not None]
        r60 = sorted(x[2] for x in g if x[2] is not None)
        if not r60:
            continue
        print(f"{k + 1:>7}{f'{g[0][0]:.3f}~{g[-1][0]:.3f}':>16}"
              f"{statistics.median(r20) * 100:>9.2f}%{statistics.median(r60) * 100:>9.2f}%"
              f"{statistics.mean(r60) * 100:>9.2f}%{r60[int(len(r60) * .9)] * 100:>8.1f}%"
              f"{r60[int(len(r60) * .1)] * 100:>8.1f}%")

    print(f"\n③ 建仓日 MA20 止损是不是已经把它吃掉了")
    print(f"{'十分位':>7}{'收/MA60':>16}{'裸持均值':>10}{'止损后均值':>11}{'裸持P10':>9}{'止损后P10':>10}{'触发率':>8}")
    for k in range(DECILES):
        g = [x for x in obs[n * k // DECILES:n * (k + 1) // DECILES] if x[2] is not None]
        if not g:
            continue
        raw = sorted(x[2] for x in g)
        stp = sorted(x[3] for x in g)
        hit = sum(1 for x in g if abs(x[2] - x[3]) > 1e-12) / len(g)
        print(f"{k + 1:>7}{f'{g[0][0]:.3f}~{g[-1][0]:.3f}':>16}"
              f"{statistics.mean(raw) * 100:>9.2f}%{statistics.mean(stp) * 100:>10.2f}%"
              f"{raw[int(len(raw) * .1)] * 100:>8.1f}%{stp[int(len(stp) * .1)] * 100:>9.1f}%{hit * 100:>7.0f}%")


if __name__ == "__main__":
    main()
