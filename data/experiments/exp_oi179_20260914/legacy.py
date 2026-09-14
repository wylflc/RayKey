"""Frozen pre-OI-179 functions from c3e90b96; research reproduction only."""
from collections import defaultdict

def daily_returns(prices: dict[str, dict[str, float]],
                  actions: dict[str, dict[str, tuple[float, float]]]) -> dict[str, dict[str, float]]:
    """逐票日收益率。**必须按送转折算**，否则除权日会被当成一次 −50% 的暴跌算进相关性。"""
    out: dict[str, dict[str, float]] = {}
    for code, series in prices.items():
        days = sorted(series)
        ret = {}
        for prev, cur in zip(days, days[1:]):
            base = series[prev]
            cash, ratio, rr, rp = actions.get(code, {}).get(cur, (0.0, 0.0, 0.0, 0.0))
            if base > 0:
                # 配股按全额认购：持有 1 股变 (1+k+rr) 股、付 rr×配股价
                ret[cur] = (series[cur] * (1 + ratio + rr) + cash - rr * rp) / base - 1
        out[code] = ret
    return out

def exright_affine(days: list[str], events: dict[str, tuple[float, float]]) -> tuple[list[float], list[float]]:
    """每个交易日「当日口径 → 末日口径」的仿射映射 `q = A·p + B`（除权折算的累积形式）。

    除权日 `e` 的事件 `(D, r, rr, rp)` 把 `e` 之前任一日的价格折到 `e` 当日口径：`p → (p − D + rr·rp)/(1 + r + rr)`
    （配股按交易所除权参考价：每股配 `rr` 股、配股价 `rp`）
    （§11.4 交易所除权参考价公式，与 `apply_corporate_actions` 对持仓锚的折算同式）。自末日向前
    累乘即可得到每一日到末日的复合映射；同一映射反过来用，就能把末日口径的均值折回任意一日的口径。
    """
    n = len(days)
    scale, shift = [1.0] * n, [0.0] * n
    a, b = 1.0, 0.0
    for i in range(n - 1, -1, -1):
        scale[i], shift[i] = a, b
        event = events.get(days[i])
        if event:                               # 第 i 日除权：i 之前的日子多一层 (p − D + rr·配股价)/(1 + r + rr)
            cash, ratio, rr, rp = event
            a, b = a / (1.0 + ratio + rr), b + a * (rr * rp - cash) / (1.0 + ratio + rr)
    return scale, shift

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
