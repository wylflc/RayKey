#!/usr/bin/env python3
"""实验 B（无选股、无估值）：纯量价信号的事件研究 + 随机抽样持有组合模拟。

**这是研究工具，不是生产流程的一部分**；结论与数据集说明见 `docs/reports/Ashare_quant_exp2_volume_price.md`。
依赖 numpy（仓库生产代码不依赖它）：本机用 `python3.11`（miniconda，自带 numpy/pandas）运行：

    python3.11 scripts/experimental/vp_signal_lab.py event \
        --signals "vol_up(r=0.05,k=2)" "ma_pullback(ma=20)" --universe all --out-dir data/experiments/exp_b
    python3.11 scripts/experimental/vp_signal_lab.py portfolio \
        --signal "vol_up(r=0.05,k=2)" --hold 20 --k 10 --seeds 30 --universe all

数据与口径
----------
* 行情：`data/raw/ohlcv/<代码>.csv`（不复权日线，含已退市股票）；交易日历取 `INDEX_000001.csv`。
* 复权：按 `data/raw/corporate_actions/a_share_corporate_actions.csv` 的现金分红与送转把**价格折到末日口径**
  （前复权：除权日前价格 × (除权参考价 ÷ 前收盘)，参考价 = (前收盘 − 每股现金) ÷ (1+送转比)），成交量反向乘 (1+送转比)。
  收益率与均线都在折算后的序列上算，即**含分红再投资的总收益口径**。
* 信号日 T 收盘出信号，**T+1 收盘买入**（与回测引擎 `--exec-delay 1 --exec-price close` 同基），持有 H 个交易日后
  T+1+H 收盘卖出；T+1 **一字板（最高=最低）或封板涨停（涨幅 ≥9.5% 且收于最高）视为买不进，剔除**；T+1 停牌剔除。
  卖出日停牌用此后最近一个收盘（退市股用末个收盘，与回测协议一致）。
* 市场基准：同日**全部可交易股票**等权的同期收益；「超额」= 个股前瞻收益 − 同日基准。
* 上市满 250 个交易日才进入样本（均线需要历史，也避开新股异常波动）。

信号以 `name(param=value,...)` 指定，名称与参数见 `SIGNALS`；新量价组合在此登记即可。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OHLCV = ROOT / "data/raw/ohlcv"
ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
CALENDAR = OHLCV / "INDEX_000001.csv"
NAMES_SRC = [ROOT / "data/raw/a_share_securities.csv", ROOT / "data/raw/a_share_delisted_roster.csv"]
HORIZONS = (3, 5, 10, 20, 60)
TARGETS = (0.02, 0.03, 0.05, 0.10)
FEES = {"commission": 0.0001, "min_fee": 5.0, "stamp": 0.0005, "transfer": 0.00001}


# ------------------------------------------------------------------ 数据
class Market:
    def __init__(self, dates: list[str], codes: list[str], o, h, l, c, v, age):
        self.dates, self.codes = dates, codes
        self.o, self.h, self.l, self.c, self.v, self.age = o, h, l, c, v, age
        self.didx = {d: i for i, d in enumerate(dates)}
        self.n, self.t = c.shape
        self._ret = None

    @property
    def ret(self):
        if self._ret is None:
            r = np.full_like(self.c, np.nan)
            r[:, 1:] = self.c[:, 1:] / self.c[:, :-1] - 1.0
            self._ret = r
        return self._ret


def load_calendar(start: str, end: str) -> list[str]:
    with CALENDAR.open(newline="", encoding="utf-8") as fh:
        days = sorted(r["date"] for r in csv.DictReader(fh) if r.get("date"))
    return [d for d in days if start <= d <= end]


def load_actions() -> dict[str, list[tuple[str, float, float]]]:
    out: dict[str, list[tuple[str, float, float]]] = {}
    if not ACTIONS.exists():
        return out
    with ACTIONS.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d = (r.get("ex_dividend_date") or "").strip()
            if not d:
                continue
            try:
                cash = float(r.get("cash_per_share") or 0); ratio = float(r.get("share_ratio") or 0)
            except ValueError:
                continue
            out.setdefault(r["security_code"].zfill(6), []).append((d, cash, ratio))
    for code in out:
        out[code].sort()
    return out


def load_market(start: str, end: str, load_from: str, max_stocks: int = 0, cache: Path | None = None) -> Market:
    if cache and cache.exists():
        z = np.load(cache, allow_pickle=False)
        dates, codes = list(z["dates"]), list(z["codes"])
        if dates[0] == load_from or dates[0] <= start:
            m = Market(dates, codes, z["o"], z["h"], z["l"], z["c"], z["v"], z["age"])
            print(f"缓存载入 {cache}：{m.n} 只 × {m.t} 日", file=sys.stderr)
            return m
    t0 = time.time()
    dates = load_calendar(load_from, end)
    didx = {d: i for i, d in enumerate(dates)}
    files = sorted(p for p in OHLCV.glob("*.csv") if p.stem.isdigit())
    if max_stocks:
        files = files[:max_stocks]
    n, t = len(files), len(dates)
    o = np.full((n, t), np.nan, np.float32); h = o.copy(); l = o.copy(); c = o.copy(); v = o.copy()
    age = np.zeros((n, t), np.int16)            # 截至当日的上市交易日数（含之前日历外的历史）
    codes = []
    actions = load_actions()
    skipped_events = 0
    for i, path in enumerate(files):
        code = path.stem
        codes.append(code)
        rows = []
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if not header:
                continue
            ix = {k: header.index(k) for k in ("date", "open", "close", "high", "low", "volume")}
            for row in reader:
                try:
                    d = row[ix["date"]]; cl = float(row[ix["close"]])
                except (ValueError, IndexError):
                    continue
                if cl <= 0:
                    continue
                rows.append((d, row))
        rows.sort(key=lambda x: x[0])
        before = sum(1 for d, _ in rows if d < load_from)
        cnt = before
        last_close_raw = {}
        for d, row in rows:
            j = didx.get(d)
            cnt += 1
            if j is None:
                continue
            try:
                o[i, j] = float(row[ix["open"]]); h[i, j] = float(row[ix["high"]]); l[i, j] = float(row[ix["low"]])
                c[i, j] = float(row[ix["close"]]); v[i, j] = float(row[ix["volume"]])
            except ValueError:
                pass
            age[i, j] = min(cnt, 32000)
        # 前复权折算：从后往前累乘
        evs = actions.get(code, [])
        if evs:
            cum = 1.0; vcum = 1.0
            factor = np.ones(t, np.float64); vfactor = np.ones(t, np.float64)
            # 事件按日期降序处理，因子累乘应用于除权日之前的所有日期
            valid = np.where(~np.isnan(c[i]))[0]
            for d, cash, ratio in sorted(evs, reverse=True):
                j = didx.get(d)
                if j is None:
                    # 除权日不在日历内（早于载入起点或非交易日）：早于起点则对本窗无影响
                    if d < load_from:
                        continue
                    # 非交易日：取其后第一个日历日位置
                    k = np.searchsorted(np.array(dates), d)
                    if k >= t:
                        continue
                    j = int(k)
                prev = valid[valid < j]
                if len(prev) == 0:
                    continue
                p = float(c[i, prev[-1]])
                ref = (p - cash) / (1.0 + ratio)
                if ref <= 0 or p <= 0:
                    skipped_events += 1
                    continue
                f = ref / p
                cum *= f; vcum *= (1.0 + ratio)
                factor[:j] = cum                # 覆盖写入（cum 已含更晚事件）
                vfactor[:j] = vcum
            for arr in (o, h, l, c):
                arr[i] = (arr[i].astype(np.float64) * factor).astype(np.float32)
            v[i] = (v[i].astype(np.float64) * vfactor).astype(np.float32)
        if (i + 1) % 500 == 0:
            print(f"  载入 {i + 1}/{n} …", file=sys.stderr)
    print(f"行情载入 {n} 只 × {t} 日（{dates[0]}~{dates[-1]}），{time.time() - t0:.0f}s；除权事件跳过 {skipped_events}", file=sys.stderr)
    m = Market(dates, codes, o, h, l, c, v, age)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cache, dates=np.array(dates), codes=np.array(codes), o=o, h=h, l=l, c=c, v=v, age=age)
        print(f"缓存写入 {cache}", file=sys.stderr)
    return m


def load_names() -> dict[str, str]:
    names = {}
    for p in NAMES_SRC:
        if not p.exists():
            continue
        with p.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                code = r.get("security_code", "").zfill(6)
                nm = r.get("security_name") or r.get("official_name") or ""
                if code and nm and code not in names:
                    names[code] = nm
    return names


# ------------------------------------------------------------------ 指标
def rolling_mean(x: np.ndarray, n: int) -> np.ndarray:
    """沿 axis=1 的简单均线；窗口内任一 NaN 则为 NaN。"""
    out = np.full(x.shape, np.nan, np.float32)
    if n <= 0 or x.shape[1] < n:
        return out
    val = np.where(np.isnan(x), 0.0, x).astype(np.float64)
    cnt = (~np.isnan(x)).astype(np.int32)
    cs = np.cumsum(val, axis=1); cc = np.cumsum(cnt, axis=1)
    s = cs[:, n - 1:].copy(); k = cc[:, n - 1:].copy()
    s[:, 1:] -= cs[:, :-n]; k[:, 1:] -= cc[:, :-n]
    res = np.where(k == n, s / n, np.nan)
    out[:, n - 1:] = res.astype(np.float32)
    return out


def rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    """沿 axis=1 的滚动最大（含当日），NaN 忽略；窗口全 NaN → NaN。倍增法，只用 O(t) 临时数组。"""
    out = np.full(x.shape, np.nan, np.float32)
    if n <= 0 or x.shape[1] < n:
        return out
    m = x.astype(np.float32, copy=True)
    span = 1
    while span * 2 <= n:
        m = np.fmax(m, shift(m, span))
        span *= 2
    if span < n:
        m = np.fmax(m, shift(m, n - span))
    out[:, n - 1:] = m[:, n - 1:]
    return out


def shift(x: np.ndarray, k: int) -> np.ndarray:
    """x[:, t-k]（k>0 向右平移取过去值）。"""
    out = np.full(x.shape, np.nan, x.dtype)
    if k > 0:
        out[:, k:] = x[:, :-k]
    elif k < 0:
        out[:, :k] = x[:, -k:]
    else:
        out[:] = x
    return out


class Ctx:
    """指标缓存：按需计算并复用。"""

    def __init__(self, m: Market):
        self.m = m
        self._cache: dict[str, np.ndarray] = {}

    def ma(self, n: int) -> np.ndarray:
        return self._get(f"ma{n}", lambda: rolling_mean(self.m.c, n))

    def vma(self, n: int, lag: int = 1) -> np.ndarray:
        """成交量均值，缺省取**前一日止**的 n 日均量（不含当日，避免当日放量抬高基准）。"""
        return self._get(f"vma{n}_l{lag}", lambda: shift(rolling_mean(self.m.v, n), lag))

    def hmax(self, n: int, lag: int = 1) -> np.ndarray:
        return self._get(f"hmax{n}_l{lag}", lambda: shift(rolling_max(self.m.h, n), lag))

    def prev_close(self) -> np.ndarray:
        return self._get("pc", lambda: shift(self.m.c, 1))

    def ret(self) -> np.ndarray:
        return self.m.ret

    def _get(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]


# ------------------------------------------------------------------ 信号登记
def sig_vol_up(ctx: Ctx, r: float = 0.05, k: float = 2.0, n: int = 20) -> np.ndarray:
    """放量上涨：当日涨幅 ≥ r，成交量 ≥ k × 前 n 日均量，且收阳（收>开）。"""
    m = ctx.m
    return (ctx.ret() >= r) & (m.v >= k * ctx.vma(n)) & (m.c > m.o)


def sig_vol_up_trend(ctx: Ctx, r: float = 0.05, k: float = 2.0, n: int = 20) -> np.ndarray:
    """放量上涨 + 收盘 > MA20 > MA60（多头背景下的放量）。"""
    m = ctx.m
    return sig_vol_up(ctx, r, k, n) & (m.c > ctx.ma(20)) & (ctx.ma(20) > ctx.ma(60))


def sig_bull_align(ctx: Ctx, fast: int = 20, mid: int = 60, slow: int = 120) -> np.ndarray:
    """多头排列：收盘 > MA_fast > MA_mid > MA_slow。"""
    m = ctx.m
    return (m.c > ctx.ma(fast)) & (ctx.ma(fast) > ctx.ma(mid)) & (ctx.ma(mid) > ctx.ma(slow))


def sig_ma_pullback(ctx: Ctx, ma: int = 20, tol: float = 0.01, slow: int = 60) -> np.ndarray:
    """多头排列回踩均线：MA_ma > MA_slow，当日最低 ≤ MA_ma×(1+tol)，收盘 ≥ MA_ma 且收阳（回踩不破、当日收回）。"""
    m = ctx.m
    a = ctx.ma(ma)
    return (a > ctx.ma(slow)) & (m.l <= a * (1 + tol)) & (m.c >= a) & (m.c > m.o) & (shift(m.c, 1) > shift(a, 1))


def sig_breakout(ctx: Ctx, n: int = 60, k: float = 1.5) -> np.ndarray:
    """放量突破：收盘 > 前 n 日最高价，成交量 ≥ k × 前 20 日均量。"""
    m = ctx.m
    return (m.c > ctx.hmax(n)) & (m.v >= k * ctx.vma(20))


def sig_limit_up(ctx: Ctx, r: float = 0.095) -> np.ndarray:
    """涨停（涨幅 ≥ r）。"""
    return ctx.ret() >= r


def sig_gap_up(ctx: Ctx, g: float = 0.03) -> np.ndarray:
    """跳空高开 ≥ g 且收阳、收盘高于前收。"""
    m = ctx.m
    pc = ctx.prev_close()
    return (m.o >= pc * (1 + g)) & (m.c >= m.o) & (m.c > pc)


def sig_golden_cross(ctx: Ctx, fast: int = 20, slow: int = 60) -> np.ndarray:
    """均线金叉：MA_fast 当日上穿 MA_slow。"""
    f, s = ctx.ma(fast), ctx.ma(slow)
    return (f > s) & (shift(f, 1) <= shift(s, 1))


def sig_three_up(ctx: Ctx, n: int = 3) -> np.ndarray:
    """连续 n 根阳线且成交量逐日放大。"""
    m = ctx.m
    ok = np.ones(m.c.shape, bool)
    for i in range(n):
        ok &= (shift(m.c, i) > shift(m.o, i)) & (shift(m.c, i) > shift(m.c, i + 1))
        if i < n - 1:
            ok &= shift(m.v, i) > shift(m.v, i + 1)
    return ok


def sig_vol_down(ctx: Ctx, r: float = -0.05, k: float = 2.0, n: int = 20) -> np.ndarray:
    """放量下跌：当日跌幅 ≤ r，成交量 ≥ k × 前 n 日均量（反转族）。"""
    m = ctx.m
    return (ctx.ret() <= r) & (m.v >= k * ctx.vma(n))


def sig_drawdown_rebound(ctx: Ctx, n: int = 5, dd: float = -0.08, up: float = 0.02) -> np.ndarray:
    """急跌后首阳：前 n 日累计跌幅 ≤ dd（不含当日），当日涨幅 ≥ up 且收阳。"""
    m = ctx.m
    prev_n = shift(m.c, 1) / shift(m.c, n + 1) - 1.0
    return (prev_n <= dd) & (ctx.ret() >= up) & (m.c > m.o)


def sig_oversold_ma(ctx: Ctx, ma: int = 20, dev: float = -0.10) -> np.ndarray:
    """超跌：收盘低于 MA_ma 达 |dev| 以上。"""
    return (ctx.m.c / ctx.ma(ma) - 1.0) <= dev


def sig_n_down(ctx: Ctx, n: int = 5) -> np.ndarray:
    """连续 n 日收跌。"""
    m = ctx.m
    ok = np.ones(m.c.shape, bool)
    for i in range(n):
        ok &= shift(m.c, i) < shift(m.c, i + 1)
    return ok


def sig_low_vol_pullback(ctx: Ctx, ma: int = 20, k: float = 0.6, n: int = 20) -> np.ndarray:
    """缩量回调到均线：MA20 > MA60，收盘在 MA20 ±2% 内，成交量 ≤ k × 前 n 日均量（多头中的缩量整理）。"""
    m = ctx.m
    a = ctx.ma(ma)
    return (a > ctx.ma(60)) & (np.abs(m.c / a - 1.0) <= 0.02) & (m.v <= k * ctx.vma(n))


def rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    return -rolling_max(-x, n)


def sig_dry_pullback_vol_up(ctx: Ctx, ma: int = 60, look: int = 10, tol: float = 0.02, brk: float = 0.03,
                            dry: float = 0.7, r: float = 0.02, k: float = 1.5) -> np.ndarray:
    """缩量回踩均线后放量阳线（用户 2026-08-22 提出）：
    ① 均线上行（MA_ma 今日 > look 日前）且回踩前收盘在均线上方（look+1 日前收盘 > 当时 MA）；
    ② 最近 look 日（不含今日）内最低价触及均线附近：min(低/MA) ≤ 1+tol，且期间收盘未有效跌破：min(收/MA) ≥ 1−brk；
    ③ 缩量：回踩期均量 ≤ dry × 回踩前的 20 日均量（look+1 日前止）；
    ④ 今日放量阳线：收>开、涨幅 ≥ r、成交量 ≥ k × 回踩期均量，且收盘 ≥ MA。"""
    m = ctx.m
    a = ctx.ma(ma)
    low_ratio = rolling_min(shift(m.l / a, 1), look)          # 过去 look 日 低/MA 的最小值
    close_ratio = rolling_min(shift(m.c / a, 1), look)
    v_pull = shift(rolling_mean(m.v, look), 1)                # 回踩期均量（不含今日）
    v_before = shift(rolling_mean(m.v, 20), look + 1)         # 回踩前 20 日均量
    rising = a > shift(a, look)
    above_before = shift(m.c, look + 1) > shift(a, look + 1)
    return (rising & above_before & (low_ratio <= 1 + tol) & (close_ratio >= 1 - brk)
            & (v_pull <= dry * v_before) & (m.c > m.o) & (ctx.ret() >= r) & (m.v >= k * v_pull) & (m.c >= a))


def sig_limit_up_dry_pullback(ctx: Ctx, r: float = 0.095, k: float = 2.0, dry: float = 0.7,
                              pull_min: float = -0.06, pull_max: float = 0.0, yin: int = 0) -> np.ndarray:
    """放量涨停后次日缩量回调（用户 2026-08-22 提出）：
    前一日涨幅 ≥ r 且成交量 ≥ k × 其前 20 日均量；当日涨跌幅在 [pull_min, pull_max] 内（缺省收跌但不超过 −6%），
    当日成交量 ≤ dry × 前一日成交量；yin=1 时另要求当日收阴（收<开）。"""
    m = ctx.m
    ret = ctx.ret()
    prev_ret, prev_v = shift(ret, 1), shift(m.v, 1)
    prev_vma = shift(ctx.vma(20), 1)                 # 前一日的"前 20 日均量"
    ok = (prev_ret >= r) & (prev_v >= k * prev_vma) & (ret >= pull_min) & (ret <= pull_max) & (m.v <= dry * prev_v)
    if yin:
        ok &= m.c < m.o
    return ok


def sig_any(ctx: Ctx) -> np.ndarray:
    """安慰剂：全部可交易股票日（无信号的随机基线）。"""
    return np.ones(ctx.m.c.shape, bool)


SIGNALS = {
    "vol_up": sig_vol_up, "vol_up_trend": sig_vol_up_trend, "bull_align": sig_bull_align,
    "ma_pullback": sig_ma_pullback, "breakout": sig_breakout, "limit_up": sig_limit_up,
    "gap_up": sig_gap_up, "golden_cross": sig_golden_cross, "three_up": sig_three_up,
    "vol_down": sig_vol_down, "drawdown_rebound": sig_drawdown_rebound, "oversold_ma": sig_oversold_ma,
    "n_down": sig_n_down, "low_vol_pullback": sig_low_vol_pullback,
    "dry_pullback_vol_up": sig_dry_pullback_vol_up, "limit_up_dry_pullback": sig_limit_up_dry_pullback, "any": sig_any,
}


def parse_signal(spec: str):
    mt = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\((.*)\))?\s*", spec)
    if not mt or mt.group(1) not in SIGNALS:
        sys.exit(f"未知信号 {spec!r}；可用：{', '.join(SIGNALS)}")
    name, argtxt = mt.group(1), mt.group(2) or ""
    kwargs = {}
    for part in argtxt.split(","):
        if part.strip():
            k, v = part.split("=")
            v = v.strip()
            kwargs[k.strip()] = int(v) if re.fullmatch(r"-?\d+", v) else float(v)
    return name, kwargs


def signal_label(name: str, kwargs: dict) -> str:
    return name + ("(" + ",".join(f"{k}={v}" for k, v in kwargs.items()) + ")" if kwargs else "")


# ------------------------------------------------------------------ 样本与前瞻收益
class Panel:
    """可交易掩码、T+1 入场价；各 H 的前瞻收益/最大有利偏移/同日市场基准**按需计算**（省内存）。"""

    def __init__(self, m: Market, universe_mask: np.ndarray, min_age: int = 250, entry: str = "close"):
        self.m = m
        c, h, l = m.c, m.h, m.l
        ret = m.ret
        # 入场（T+1）：有价、非一字板、非封板涨停
        nxt_c, nxt_h, nxt_l, nxt_o = shift(c, -1), shift(h, -1), shift(l, -1), shift(m.o, -1)
        nxt_ret = shift(ret, -1)
        sealed = (nxt_ret >= 0.095) & (nxt_c >= nxt_h - 1e-6)
        one_line = (nxt_h <= nxt_l + 1e-6)
        self.entry_px = (nxt_o if entry == "open" else nxt_c).astype(np.float32)
        self.tradable = (universe_mask & (m.age >= min_age) & ~np.isnan(c) & ~np.isnan(self.entry_px)
                         & ~sealed & ~one_line)
        del nxt_c, nxt_h, nxt_l, nxt_o, nxt_ret, sealed, one_line
        self.cf = ffill(c)                       # 卖出价：停牌/退市用此前最近收盘
        self._fwd: dict[int, np.ndarray] = {}
        self._mfe: dict[int, np.ndarray] = {}
        self._mkt: dict[int, np.ndarray] = {}

    def fwd(self, H: int) -> np.ndarray:
        if H not in self._fwd:
            exit_px = shift(self.cf, -(1 + H))
            tail = np.broadcast_to(self.cf[:, -1:], self.cf.shape)
            exit_px = np.where(np.isnan(exit_px), tail, exit_px)      # 超出末日：按末日收盘截尾
            f = (exit_px / self.entry_px - 1.0).astype(np.float32)
            f[~self.tradable] = np.nan
            self._fwd[H] = f
            self._mkt[H] = np.nanmean(f, axis=0)                      # 同日可交易股票等权
        return self._fwd[H]

    def mkt(self, H: int) -> np.ndarray:
        self.fwd(H)
        return self._mkt[H]

    def mfe(self, H: int) -> np.ndarray:
        if H not in self._mfe:
            hm = rolling_max(self.m.h, H)                 # 含当日的 H 日最高
            x = (shift(hm, -(1 + H)) / self.entry_px - 1.0).astype(np.float32)   # 覆盖 T+2..T+1+H
            x[~self.tradable] = np.nan
            self._mfe[H] = x
        return self._mfe[H]

    def drop(self, H: int) -> None:
        self._fwd.pop(H, None); self._mfe.pop(H, None)


def ffill(x: np.ndarray) -> np.ndarray:
    out = x.copy()
    mask = np.isnan(out)
    idx = np.where(~mask, np.arange(x.shape[1], dtype=np.int32), 0).astype(np.int32)
    np.maximum.accumulate(idx, axis=1, out=idx)
    out = out[np.arange(x.shape[0])[:, None], idx]
    out[mask & (idx == 0) & np.isnan(x[:, :1])] = np.nan
    return out


def universe_mask(m: Market, spec: str) -> np.ndarray:
    """`all` 或股票库面板 CSV（effective_from/effective_to/security_code）。"""
    if spec == "all":
        return np.ones(m.c.shape, bool)
    mask = np.zeros(m.c.shape, bool)
    cidx = {c: i for i, c in enumerate(m.codes)}
    dates = np.array(m.dates)
    with open(spec, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            i = cidx.get(r["security_code"].zfill(6))
            if i is None:
                continue
            a = int(np.searchsorted(dates, r["effective_from"]))
            to = (r.get("effective_to") or "").strip()
            b = int(np.searchsorted(dates, to, side="right")) if to else m.t
            if b > a:
                mask[i, a:b] = True
    return mask


# ------------------------------------------------------------------ 事件研究
def event_study(m: Market, panel: Panel, sig: np.ndarray, label: str, years: list[str]) -> tuple[list[dict], list[dict]]:
    ev = sig & panel.tradable
    rows, yrows = [], []
    yr = np.array([d[:4] for d in m.dates])
    for H in HORIZONS:
        fw = panel.fwd(H)
        f = fw[ev]; exc = (fw - panel.mkt(H)[None, :])[ev]; x = panel.mfe(H)[ev]
        ok = ~np.isnan(f)
        f, exc, x = f[ok], exc[ok], x[ok]
        if len(f):
            # 按日等权（每日先对当日事件取均值，再对有事件的日子取均值）——对应"每天随机抽 K 只"的组合权重，
            # 与按事件等权的差距就是"信号在时间上扎堆"的效应
            fz = np.where(ev, fw, np.nan)
            with np.errstate(all="ignore"):
                day_mean = np.nanmean(fz, axis=0)
            day_ok = ~np.isnan(day_mean)
            dw_mean = float(np.mean(day_mean[day_ok])) if day_ok.any() else float("nan")
            dw_exc = float(np.mean((day_mean - panel.mkt(H))[day_ok])) if day_ok.any() else float("nan")
            rows.append({
                "signal": label, "H": H, "N": int(len(f)), "days": int(day_ok.sum()),
                "dw_mean": dw_mean, "dw_excess": dw_exc,
                "mean": float(np.mean(f)), "median": float(np.median(f)), "win": float(np.mean(f > 0)),
                "p_ge_2": float(np.mean(f >= 0.02)), "p_ge_5": float(np.mean(f >= 0.05)),
                "mean_excess": float(np.mean(exc)), "excess_win": float(np.mean(exc > 0)),
                "mkt_mean": float(np.mean(f) - np.mean(exc)),
                **{f"mfe_ge_{int(t * 100)}": float(np.nanmean(x >= t)) for t in TARGETS},
                "mfe_mean": float(np.nanmean(x)),
            })
        if H == 20:
            for y in years:
                col = yr == y
                evy = ev & col[None, :]
                fy = fw[evy]; ey = (fw - panel.mkt(H)[None, :])[evy]
                oky = ~np.isnan(fy)
                fy, ey = fy[oky], ey[oky]
                if len(fy) == 0:
                    yrows.append({"signal": label, "year": y, "N": 0})
                    continue
                yrows.append({"signal": label, "year": y, "N": int(len(fy)), "mean20": float(np.mean(fy)),
                              "win20": float(np.mean(fy > 0)), "excess20": float(np.mean(ey)),
                              "excess_win20": float(np.mean(ey > 0)), "days_with_signal": int(evy.any(axis=0).sum())})
        panel.drop(H)
    return rows, yrows


# ------------------------------------------------------------------ 组合模拟
def trade_fee(amount: float, side: str) -> float:
    fee = max(amount * FEES["commission"], FEES["min_fee"]) + amount * FEES["transfer"]
    if side == "sell":
        fee += amount * FEES["stamp"]
    return fee


def simulate(m: Market, panel: Panel, sig: np.ndarray, hold: int, k: int, seed: int,
             capital: float, target: float = 0.0, start: int = 0, end: int | None = None,
             max_weight: float = 1.0) -> dict:
    """H 个滚动档位：每日把到期档位的资金重新投入当日信号股（随机 K 只，等权）。

    `target>0`：入场后任一日最高价 ≥ 入场价×(1+target) 即按目标价卖出（挂单成交假设），否则到期按收盘卖。
    """
    rng = np.random.default_rng(seed)
    c = m.c; h = m.h
    cf = panel.cf
    T = m.t if end is None else end
    ev = sig & panel.tradable
    slots = [None] * hold            # 每档：dict(entry_day, positions=[(i, shares, entry_px)], cash)
    slot_cash = [capital / hold] * hold
    equity = np.full(T, np.nan)
    n_pos = np.zeros(T, np.int16)
    turnover = 0.0
    trades = 0
    wins = 0
    gross = []
    for t in range(start, T):
        s = t % hold
        # 1) 到期档位卖出（持有 hold 日：在 t 日以 t 日收盘/目标价退出）
        slot = slots[s]
        if slot is not None:
            cash = 0.0
            for (i, shares, px, tgt_px) in slot["pos"]:
                sold = False
                if tgt_px > 0:
                    # 在 (entry_day, t] 内首次触及目标价
                    e = slot["entry_day"]
                    seg = h[i, e + 1:t + 1]
                    hit = np.where(seg >= tgt_px)[0]
                    if len(hit):
                        exit_px = tgt_px; sold = True
                if not sold:
                    exit_px = cf[i, t]
                    if np.isnan(exit_px):
                        exit_px = px
                amt = shares * exit_px
                cash += amt - trade_fee(amt, "sell")
                turnover += amt
                trades += 1
                gross.append(exit_px / px - 1.0)
                if exit_px > px:
                    wins += 1
            slot_cash[s] += cash
            slots[s] = None
        # 2) 当日信号 → 用本档现金买入（T 日收盘信号，T+1 收盘成交：这里 t 是成交日，信号取 t-1）
        if t >= 1:
            cand = np.where(ev[:, t - 1])[0]
            if len(cand) and slot_cash[s] > 0:
                pick = cand if len(cand) <= k else rng.choice(cand, size=k, replace=False)
                budget = slot_cash[s] / len(pick)
                pos = []
                spent = 0.0
                for i in pick:
                    px = float(panel.entry_px[i, t - 1])
                    if not (px > 0):
                        continue
                    shares = math.floor(budget / (px * 100)) * 100
                    if shares <= 0:
                        continue
                    amt = shares * px
                    fee = trade_fee(amt, "buy")
                    spent += amt + fee
                    turnover += amt
                    pos.append((int(i), shares, px, px * (1 + target) if target > 0 else 0.0))
                if pos:
                    slots[s] = {"entry_day": t, "pos": pos}
                    slot_cash[s] -= spent
        # 3) 盯市
        val = sum(slot_cash)
        cnt = 0
        for sl in slots:
            if sl is None:
                continue
            for (i, shares, px, _tgt) in sl["pos"]:
                p = cf[i, t]
                val += shares * (px if np.isnan(p) else p)
                cnt += 1
        equity[t] = val
        n_pos[t] = cnt
    eq = equity[start:T]
    eq = eq[~np.isnan(eq)]
    years = (len(eq) - 1) / 244.0
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1 if years > 0 and eq[0] > 0 and eq[-1] > 0 else float("nan")
    peak = np.maximum.accumulate(eq)
    mdd = float(np.max(1 - eq / peak)) if len(eq) else float("nan")
    dr = eq[1:] / eq[:-1] - 1
    sharpe = float(np.mean(dr) / np.std(dr) * math.sqrt(244)) if len(dr) > 2 and np.std(dr) > 0 else float("nan")
    # 逐年
    yr = np.array([d[:4] for d in m.dates[start:T]])
    yearly = {}
    eq_full = equity[start:T]
    for y in sorted(set(yr)):
        idx = np.where(yr == y)[0]
        a, b = eq_full[idx[0]], eq_full[idx[-1]]
        prev = eq_full[idx[0] - 1] if idx[0] > 0 and not np.isnan(eq_full[idx[0] - 1]) else a
        if prev > 0 and b > 0:
            yearly[y] = b / prev - 1
    return {"seed": seed, "cagr": cagr, "mdd": mdd, "sharpe": sharpe, "final": float(eq[-1]),
            "trades": trades, "win_rate": wins / trades if trades else float("nan"),
            "avg_gross": float(np.mean(gross)) if gross else float("nan"),
            "turnover_per_year": turnover / capital / years if years > 0 else float("nan"),
            "avg_positions": float(np.mean(n_pos[start:T])), "yearly": yearly}


# ------------------------------------------------------------------ 主程序
def fmt_pct(x) -> str:
    return "" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x * 100:.2f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--start", default="2005-01-04", help="样本起点（信号日）")
    common.add_argument("--end", default="2026-08-07")
    common.add_argument("--load-from", default="2003-01-01", help="行情载入起点（均线需要前置历史）")
    common.add_argument("--universe", default="all", help="all 或股票库面板 CSV")
    common.add_argument("--min-age", type=int, default=250)
    common.add_argument("--entry", choices=("close", "open"), default="close", help="T+1 入场价")
    common.add_argument("--max-stocks", type=int, default=0, help="调试：只载入前 N 只")
    common.add_argument("--cache", type=Path, default=ROOT / "data/interim/exp_b_market_cache.npz")
    common.add_argument("--no-cache", action="store_true")
    common.add_argument("--out-dir", type=Path, default=ROOT / "data/experiments/exp_b")
    common.add_argument("--tag", default="", help="输出文件名附加标记")
    e = sub.add_parser("event", parents=[common], help="事件研究")
    e.add_argument("--signals", nargs="+", required=True)
    p = sub.add_parser("portfolio", parents=[common], help="随机抽样持有组合")
    p.add_argument("--signal", required=True)
    p.add_argument("--hold", type=int, nargs="+", default=[20])
    p.add_argument("--k", type=int, nargs="+", default=[10])
    p.add_argument("--seeds", type=int, default=20)
    p.add_argument("--capital", type=float, default=3_000_000)
    p.add_argument("--target", type=float, nargs="+", default=[0.0], help="目标价卖出比例，0=不挂单")
    p.add_argument("--placebo", action="store_true", help="同时跑 any() 安慰剂对照")
    args = ap.parse_args()

    cache = None if args.no_cache or args.max_stocks else args.cache
    m = load_market(args.start, args.end, args.load_from, args.max_stocks, cache)
    start_i = int(np.searchsorted(np.array(m.dates), args.start))
    umask = universe_mask(m, args.universe)
    uni_label = "all" if args.universe == "all" else Path(args.universe).stem
    ctx = Ctx(m)
    panel = Panel(m, umask, args.min_age, args.entry)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    years = sorted({d[:4] for d in m.dates[start_i:]})
    in_range = np.zeros(m.t, bool); in_range[start_i:] = True

    if args.cmd == "event":
        all_rows, all_yrows = [], []
        for spec in args.signals:
            name, kw = parse_signal(spec)
            label = signal_label(name, kw)
            sig = SIGNALS[name](ctx, **kw) & in_range[None, :]
            rows, yrows = event_study(m, panel, sig, label, years)
            all_rows += rows; all_yrows += yrows
            print(f"\n## {label}｜宇宙 {uni_label}｜入场 T+1 {args.entry}")
            print(f"{'H':>3} {'N':>9} {'均值':>8} {'中位':>8} {'胜率':>7} {'≥2%':>7} {'≥5%':>7} {'超额均值':>9} {'超额胜率':>9} {'市场均值':>9} "
                  + " ".join(f"{'曾≥' + str(int(t * 100)) + '%':>8}" for t in TARGETS) + f" {'日权均值':>9} {'日权超额':>9}")
            for r in rows:
                print(f"{r['H']:>3} {r['N']:>9,} {fmt_pct(r['mean']):>8} {fmt_pct(r['median']):>8} {fmt_pct(r['win']):>7} "
                      f"{fmt_pct(r['p_ge_2']):>7} {fmt_pct(r['p_ge_5']):>7} {fmt_pct(r['mean_excess']):>9} {fmt_pct(r['excess_win']):>9} {fmt_pct(r['mkt_mean']):>9} "
                      + " ".join(f"{fmt_pct(r[f'mfe_ge_{int(t * 100)}']):>8}" for t in TARGETS)
                      + f" {fmt_pct(r['dw_mean']):>9} {fmt_pct(r['dw_excess']):>9}")
            print("  逐年（H=20）：" + "；".join(
                f"{r['year']} N={r['N']:,} 均{fmt_pct(r.get('mean20'))} 胜{fmt_pct(r.get('win20'))} 超{fmt_pct(r.get('excess20'))}"
                for r in yrows if r["N"]))
        tag = f"_{args.tag}" if args.tag else ""
        with (args.out_dir / f"event_{uni_label}{tag}.csv").open("w", newline="", encoding="utf-8") as fh:
            keys = list(all_rows[0].keys()) if all_rows else ["signal"]
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(all_rows)
        with (args.out_dir / f"event_yearly_{uni_label}{tag}.csv").open("w", newline="", encoding="utf-8") as fh:
            keys = ["signal", "year", "N", "mean20", "win20", "excess20", "excess_win20", "days_with_signal"]
            w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(all_yrows)
        print(f"\n写入 {args.out_dir}/event_{uni_label}{tag}.csv 与 event_yearly_{uni_label}{tag}.csv")
        return

    # portfolio
    name, kw = parse_signal(args.signal)
    label = signal_label(name, kw)
    sig = SIGNALS[name](ctx, **kw) & in_range[None, :]
    arms = [(label, sig)]
    if args.placebo:
        arms.append(("any()", sig_any(ctx) & in_range[None, :]))
    out_rows = []
    for arm_label, arm_sig in arms:
        for hold in args.hold:
            for k in args.k:
                for target in args.target:
                    res = [simulate(m, panel, arm_sig, hold, k, seed, args.capital, target, start_i) for seed in range(args.seeds)]
                    cagr = np.array([r["cagr"] for r in res]); mdd = np.array([r["mdd"] for r in res])
                    row = {"signal": arm_label, "universe": uni_label, "hold": hold, "k": k, "target": target, "seeds": args.seeds,
                           "cagr_median": float(np.nanmedian(cagr)), "cagr_p10": float(np.nanpercentile(cagr, 10)),
                           "cagr_p90": float(np.nanpercentile(cagr, 90)), "cagr_pos_share": float(np.mean(cagr > 0)),
                           "mdd_median": float(np.nanmedian(mdd)),
                           "sharpe_median": float(np.nanmedian([r["sharpe"] for r in res])),
                           "trades_mean": float(np.mean([r["trades"] for r in res])),
                           "win_rate_mean": float(np.nanmean([r["win_rate"] for r in res])),
                           "avg_gross_mean": float(np.nanmean([r["avg_gross"] for r in res])),
                           "turnover_mean": float(np.nanmean([r["turnover_per_year"] for r in res])),
                           "avg_positions": float(np.mean([r["avg_positions"] for r in res]))}
                    # 逐年中位
                    ys = sorted({y for r in res for y in r["yearly"]})
                    row["yearly_median"] = json.dumps({y: round(float(np.median([r["yearly"][y] for r in res if y in r["yearly"]])), 4) for y in ys})
                    out_rows.append(row)
                    print(f"\n## {arm_label}｜宇宙 {uni_label}｜H={hold} K={k} 目标={target:.0%} 种子 {args.seeds}")
                    print(f"  年化 中位 {fmt_pct(row['cagr_median'])}（P10 {fmt_pct(row['cagr_p10'])} / P90 {fmt_pct(row['cagr_p90'])}，为正 {row['cagr_pos_share']:.0%}）｜"
                          f"最大回撤中位 {fmt_pct(row['mdd_median'])}｜Sharpe {row['sharpe_median']:.2f}｜笔数 {row['trades_mean']:.0f}｜"
                          f"单笔胜率 {fmt_pct(row['win_rate_mean'])}｜单笔毛收益 {fmt_pct(row['avg_gross_mean'])}｜年换手 {row['turnover_mean']:.1f}x｜均持仓 {row['avg_positions']:.1f}")
                    print("  逐年中位：" + " ".join(f"{y}:{float(v) * 100:+.1f}%" for y, v in json.loads(row["yearly_median"]).items()))
    tag = f"_{args.tag}" if args.tag else ""
    path = args.out_dir / f"portfolio_{uni_label}{tag}.csv"
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        if not exists:
            w.writeheader()
        w.writerows(out_rows)
    print(f"\n追加写入 {path}")


if __name__ == "__main__":
    main()
