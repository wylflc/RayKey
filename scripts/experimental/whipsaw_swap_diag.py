#!/usr/bin/env python3
"""换仓卖出源弱势的形态复核——交易细节复盘（用户 2026-09-06 研究思路：提案→回测→看细节→区分走势→再回测）。

读 `data/experiments/exp_whipsaw_swap/bt<起点>/<臂>/` 下的 `ledger.csv`（--trade-log）、`blocked.csv`（--weak-block-log）、
`*_trades.csv`（周期产物，含 contrib）与 `summary_*.csv`，出四段：

A. **BASE 换仓卖出的走势解剖**：每一笔 P/V 边际换仓卖出（不含涨幅让位），按信号日形态（收盘对 MA20 的偏离、连续线下日数、
   MA20 斜率、近 20 日穿越次数、MA20/MA60）与其后走势（成交日起 5／10／20／60 日前复权收益、几日内站回 MA20）分两类：
   **假摔**（whipsaw：10 日内站回 MA20 且 20 日收益 ≥ 0）与 **走坏**（breakdown：20 日收益 ≤ −5% 或 20 日内未站回 MA20），
   其余为**中间**。再报每条候选判据在两类上各挡下多少——这就是「能否区分两种走势」的直接读数。
B. **各臂被挡事件的其后走势**：被挡的卖出源与触发候选自成交日起 20／60 日收益及其差；挡对（源其后跑赢候选）还是挡错。
C. **各臂对 BASE 的流水差异**：首个分歧日、P/V 换仓卖出笔数、买卖笔数、按代码 contrib 差的前三集中度（§12.1 第 11 款同尺）。
D. 单起点 summary 读数（年化／最大回撤／换手）——只作定向，不作决策读数（决策读数看 14 起点扫描报表）。

用法::
    python3 scripts/experimental/whipsaw_swap_diag.py --exp data/experiments/exp_whipsaw_swap/bt2011 [--base BASE] [--out 报告.txt]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import glob
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import backtest_valuation_strategy as bt  # noqa: E402

PAT_SWAP = re.compile(r"^换仓(?:·减一档)?(?P<tag>·[^：]*)?：让位给(?:空间更大的)?(?P<tgt>\d{6})")
HORIZONS = (5, 10, 20, 60)


def med(xs):
    xs = [x for x in xs if x == x]
    return statistics.median(xs) if xs else float("nan")


def f(x, w=7, p=1, scale=100.0):
    return f"{'—':>{w}}" if x != x else f"{x * scale:>{w}.{p}f}"


class Market:
    """涉及代码的前复权收盘与均线（引擎同一函数），供形态与前向收益计算。"""

    def __init__(self, codes: set[str]):
        raw = bt.load_prices(codes)
        actions = bt.load_actions()
        self.days: dict[str, list[str]] = {}
        self.adj: dict[str, list[float]] = {}
        self.pos: dict[str, dict[str, int]] = {}
        self.ma: dict[str, dict[str, dict[int, float]]] = {}
        for c, series in raw.items():
            if not series:
                continue
            ev = actions.get(c, {})
            adj = bt.adjusted_close_series(series, ev)
            ds = sorted(series)
            self.days[c] = ds
            self.adj[c] = [adj[d] for d in ds]
            self.pos[c] = {d: i for i, d in enumerate(ds)}
            self.ma[c] = bt.adjusted_moving_averages(series, ev, (20, 60))
        self.raw = raw

    def idx(self, c: str, day: str) -> int | None:
        return self.pos.get(c, {}).get(day)

    def prev_day(self, c: str, day: str) -> str | None:
        i = self.idx(c, day)
        return self.days[c][i - 1] if i else None

    def fwd(self, c: str, day: str, n: int) -> float:
        i = self.idx(c, day)
        if i is None or i + n >= len(self.adj[c]):
            return float("nan")
        return self.adj[c][i + n] / self.adj[c][i] - 1.0

    def fwd_min(self, c: str, day: str, n: int) -> float:
        i = self.idx(c, day)
        if i is None or i + 1 >= len(self.adj[c]):
            return float("nan")
        base = self.adj[c][i]
        return min(self.adj[c][i + 1:i + n + 1]) / base - 1.0

    def back_above_within(self, c: str, day: str, n: int) -> int | None:
        """自 day 起 n 日内首次「不复权收盘 ≥ 当日 MA20」的日数（含 day 当日为 0）；没有为 None。"""
        i = self.idx(c, day)
        if i is None:
            return None
        for k in range(0, n + 1):
            if i + k >= len(self.days[c]):
                return None
            d = self.days[c][i + k]
            m = self.ma[c].get(d, {}).get(20)
            if m is not None and self.raw[c][d] >= m:
                return k
        return None

    def features(self, c: str, sday: str) -> dict:
        """信号日形态：gap=收盘/MA20−1；run=连续线下日数；slope_k=MA20/MA20[−k]−1；cross20=近 20 日穿越次数；ma_ratio=MA20/MA60−1。"""
        i = self.idx(c, sday)
        out = {"gap": float("nan"), "run": 0, "slope3": float("nan"), "slope5": float("nan"), "slope10": float("nan"),
               "cross20": 0, "ma_ratio": float("nan")}
        if i is None:
            return out
        ds = self.days[c]
        m = self.ma[c].get(sday, {})
        m20, m60 = m.get(20), m.get(60)
        close = self.raw[c][sday]
        if m20:
            out["gap"] = close / m20 - 1.0
        if m20 and m60:
            out["ma_ratio"] = m20 / m60 - 1.0
        for k in (3, 5, 10):
            if i - k >= 0:
                mp = self.ma[c].get(ds[i - k], {}).get(20)
                if m20 and mp:
                    out[f"slope{k}"] = m20 / mp - 1.0
        run = 0
        for j in range(i, -1, -1):
            mj = self.ma[c].get(ds[j], {}).get(20)
            if mj is None or self.raw[c][ds[j]] >= mj:
                break
            run += 1
        out["run"] = run
        flags = []
        for j in range(max(0, i - 19), i + 1):
            mj = self.ma[c].get(ds[j], {}).get(20)
            flags.append(None if mj is None else self.raw[c][ds[j]] < mj)
        out["cross20"] = sum(1 for a, b in zip(flags, flags[1:]) if a is not None and b is not None and a != b)
        return out


def read_ledger(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def swap_sells(rows: list[dict]) -> list[dict]:
    """P/V 边际换仓卖出（不含涨幅让位）。"""
    out = []
    for r in rows:
        if r["action"] != "卖出":
            continue
        m = PAT_SWAP.match(r["reason"])
        if not m or (m.group("tag") and "涨幅" in m.group("tag")) or (m.group("tag") and "阶梯" in m.group("tag")):
            continue
        out.append({**r, "target": m.group("tgt")})
    return out


def classify(mk: Market, code: str, exec_day: str) -> tuple[str, dict]:
    r = {h: mk.fwd(code, exec_day, h) for h in HORIZONS}
    back = mk.back_above_within(code, exec_day, 20)
    r["back"] = back
    r["min20"] = mk.fwd_min(code, exec_day, 20)
    r20 = r[20]
    if r20 != r20:
        return "无后续", r
    if back is not None and back <= 10 and r20 >= 0:
        return "假摔", r
    if r20 <= -0.05 or back is None:
        return "走坏", r
    return "中间", r


RULES = {
    "WK2  连续≥2日": lambda ft: ft["run"] < 2,
    "WK3  连续≥3日": lambda ft: ft["run"] < 3,
    "WK5  连续≥5日": lambda ft: ft["run"] < 5,
    "SLP3 MA20↓(3日)": lambda ft: not (ft["slope3"] < 0),
    "SLP5 MA20↓(5日)": lambda ft: not (ft["slope5"] < 0),
    "SLP10 MA20↓(10日)": lambda ft: not (ft["slope10"] < 0),
    "XC2  穿越<2": lambda ft: ft["cross20"] >= 2,
    "XC3  穿越<3": lambda ft: ft["cross20"] >= 3,
    "XC4  穿越<4": lambda ft: ft["cross20"] >= 4,
    "GAP1 偏离≤−1%": lambda ft: not (ft["gap"] <= -0.01),
    "GAP2 偏离≤−2%": lambda ft: not (ft["gap"] <= -0.02),
    "GAP3 偏离≤−3%": lambda ft: not (ft["gap"] <= -0.03),
    "MA20<MA60": lambda ft: not (ft["ma_ratio"] < 0),
}


def section_a(mk: Market, base_rows: list[dict], out) -> None:
    events = swap_sells(base_rows)
    print(f"A. BASE 的 P/V 边际换仓卖出 {len(events)} 笔（成交日口径；信号日 = 该票行情日历上的前一交易日）", file=out)
    recs = []
    for e in events:
        c, d = e["security_code"], e["date"]
        sday = mk.prev_day(c, d)
        if sday is None:
            continue
        ft = mk.features(c, sday)
        cls, r = classify(mk, c, d)
        tgt = e["target"]
        rt = {h: mk.fwd(tgt, d, h) for h in HORIZONS}
        recs.append({"code": c, "date": d, "sday": sday, "cls": cls, "ft": ft, "r": r, "rt": rt, "tgt": tgt,
                     "amount": float(e["amount"])})
    by = defaultdict(list)
    for rec in recs:
        by[rec["cls"]].append(rec)
    print(f"{'类别':<6}{'笔数':>5}{'金额中位':>10} | 信号日形态中位：{'偏离%':>6}{'连续日':>6}{'斜率5%':>7}{'斜率10%':>8}{'穿越20':>7}{'MA20/60%':>9}"
          f" | 其后源收益中位%：{'5日':>6}{'10日':>6}{'20日':>6}{'60日':>6}{'最低20':>7} | 候选20/60%：{'':>4}", file=out)
    for cls in ("假摔", "中间", "走坏", "无后续"):
        rs = by.get(cls, [])
        if not rs:
            continue
        fts = [x["ft"] for x in rs]
        print(f"{cls:<6}{len(rs):>5}{med([x['amount'] for x in rs])/1e4:>9.1f}万 | "
              f"{f(med([t['gap'] for t in fts]),6)}{med([t['run'] for t in fts]):>6.0f}{f(med([t['slope5'] for t in fts]),7,2)}"
              f"{f(med([t['slope10'] for t in fts]),8,2)}{med([t['cross20'] for t in fts]):>7.0f}{f(med([t['ma_ratio'] for t in fts]),9)}"
              f" | {''.join(f(med([x['r'][h] for x in rs]),6) for h in HORIZONS)}{f(med([x['r']['min20'] for x in rs]),7)}"
              f" | {f(med([x['rt'][20] for x in rs]),6)}{f(med([x['rt'][60] for x in rs]),6)}", file=out)
    valid = [x for x in recs if x["cls"] != "无后续"]
    if valid:
        rel20 = [x["r"][20] - x["rt"][20] for x in valid if x["rt"][20] == x["rt"][20]]
        rel60 = [x["r"][60] - x["rt"][60] for x in valid if x["rt"][60] == x["rt"][60]]
        print(f"  全部换仓：源−候选 20 日收益差中位 {f(med(rel20),0)}%（源占优 {sum(1 for v in rel20 if v > 0)}/{len(rel20)}）；"
              f"60 日 {f(med(rel60),0)}%（源占优 {sum(1 for v in rel60 if v > 0)}/{len(rel60)}）", file=out)
    print(f"\n  候选判据在两类上各挡下多少（挡下＝该笔换仓在该判据下不会发生；理想判据：挡假摔多、挡走坏少）", file=out)
    print(f"  {'判据':<18}{'挡假摔':>10}{'挡中间':>10}{'挡走坏':>10}{'挡下笔源−候选20日中位%':>20}{'放行笔源−候选20日中位%':>20}", file=out)
    for name, blocked in RULES.items():
        cnt = {}
        for cls in ("假摔", "中间", "走坏"):
            rs = by.get(cls, [])
            cnt[cls] = (sum(1 for x in rs if blocked(x["ft"])), len(rs))
        blk = [x["r"][20] - x["rt"][20] for x in valid if blocked(x["ft"]) and x["rt"][20] == x["rt"][20]]
        pas = [x["r"][20] - x["rt"][20] for x in valid if not blocked(x["ft"]) and x["rt"][20] == x["rt"][20]]
        print(f"  {name:<18}" + "".join(f"{cnt[c][0]:>5}/{cnt[c][1]:<4}" for c in ("假摔", "中间", "走坏"))
              + f"{f(med(blk),14,1)} (n={len(blk):<3}){f(med(pas),12,1)} (n={len(pas)})", file=out)
    return recs


def section_b(mk: Market, exp: Path, arms: list[str], out) -> None:
    print(f"\nB. 各臂被形态复核挡下的换仓卖出（本会被选中且边际成立）其后走势——源 vs 触发候选，自成交日起", file=out)
    print(f"  {'臂':<10}{'被挡':>5}{'假摔':>5}{'中间':>5}{'走坏':>5} | 源收益中位%：{'20日':>6}{'60日':>6} | 候选：{'20日':>6}{'60日':>6}"
          f" | 源−候选中位%：{'20日':>6}{'60日':>6}{'源占优20日':>10}{'挡下后换了别的':>14}", file=out)
    for arm in arms:
        p = exp / arm / "blocked.csv"
        if not p.exists():
            continue
        rows = read_ledger(p)
        if not rows:
            print(f"  {arm:<10}{0:>5}", file=out)
            continue
        cls = defaultdict(int)
        r20 = []; r60 = []; t20 = []; t60 = []; rel20 = []; rel60 = []; nxt = 0
        for r in rows:
            c, d, t = r["source_code"], r["exec_date"], r["trigger_code"]
            k, rr = classify(mk, c, d)
            cls[k] += 1
            r20.append(rr[20]); r60.append(rr[60])
            a, b = mk.fwd(t, d, 20), mk.fwd(t, d, 60)
            t20.append(a); t60.append(b)
            if rr[20] == rr[20] and a == a:
                rel20.append(rr[20] - a)
            if rr[60] == rr[60] and b == b:
                rel60.append(rr[60] - b)
            nxt += bool(r.get("next_source"))
        print(f"  {arm:<10}{len(rows):>5}{cls['假摔']:>5}{cls['中间']:>5}{cls['走坏']:>5} | {f(med(r20),6)}{f(med(r60),6)}"
              f" | {f(med(t20),6)}{f(med(t60),6)} | {f(med(rel20),6)}{f(med(rel60),6)}"
              f"{sum(1 for v in rel20 if v > 0):>5}/{len(rel20):<5}{nxt:>8}/{len(rows)}", file=out)


def contrib_by_code(path: Path) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["security_code"]] += float(r.get("contrib") or 0.0)
    return out


def section_c(exp: Path, base: str, arms: list[str], base_rows: list[dict], names: dict[str, str], out) -> None:
    print(f"\nC. 各臂对 {base} 的流水差异（2011-11-01 单起点）", file=out)
    base_key = [(r["date"], r["security_code"], r["action"], r["shares"]) for r in base_rows]
    base_swaps = len(swap_sells(base_rows))
    tr_base = glob.glob(str(exp / base / "*_trades.csv"))
    cb = contrib_by_code(Path(tr_base[0])) if tr_base else {}
    print(f"  {'臂':<10}{'首个分歧日':>12}{'P/V换仓卖':>9}{'卖出笔':>7}{'买入笔':>7}{'被挡':>5} | Δcontrib 前三（代码 Δpp）与净额占比", file=out)
    print(f"  {base:<10}{'—':>12}{base_swaps:>9}{sum(1 for r in base_rows if r['action']=='卖出'):>7}"
          f"{sum(1 for r in base_rows if r['action']=='买入'):>7}{'—':>5}", file=out)
    for arm in arms:
        p = exp / arm / "ledger.csv"
        if not p.exists():
            continue
        rows = read_ledger(p)
        key = [(r["date"], r["security_code"], r["action"], r["shares"]) for r in rows]
        first = next((k[0] for k, b in zip(key, base_key) if k != b), None)
        if first is None and len(key) != len(base_key):
            first = (key[len(base_key)] if len(key) > len(base_key) else base_key[len(key)])[0]
        nblk = len(read_ledger(exp / arm / "blocked.csv")) if (exp / arm / "blocked.csv").exists() else 0
        tr = glob.glob(str(exp / arm / "*_trades.csv"))
        txt = ""
        if tr and cb:
            ca = contrib_by_code(Path(tr[0]))
            delta = {c: ca.get(c, 0.0) - cb.get(c, 0.0) for c in set(ca) | set(cb)}
            tot = sum(delta.values())
            top = sorted(delta.items(), key=lambda kv: -abs(kv[1]))[:3]
            share = (sum(v for _, v in top) / tot) if tot else float("nan")
            txt = "  ".join(f"{c}{names.get(c, '')} {v*100:+.1f}" for c, v in top) + f" ｜ ΣΔ {tot*100:+.1f}pp，前三净额占比 {f(share,0,0)}%"
        print(f"  {arm:<10}{(first or '无分歧'):>12}{len(swap_sells(rows)):>9}{sum(1 for r in rows if r['action']=='卖出'):>7}"
              f"{sum(1 for r in rows if r['action']=='买入'):>7}{nblk:>5} | {txt}", file=out)


def section_d(exp: Path, base: str, arms: list[str], out) -> None:
    print(f"\nD. 单起点 summary（只作定向；决策读数看 14 起点扫描报表）", file=out)
    print(f"  {'臂':<10}{'年化%':>7}{'最大回撤%':>9}{'滚5中位%':>8}{'换手':>6}{'仓位%':>6}{'Δ年化pp':>8}", file=out)
    def read(arm):
        ps = glob.glob(str(exp / arm / "summary_*.csv"))
        if not ps:
            return None
        rs = [r for r in csv.DictReader(open(ps[0], encoding="utf-8")) if r["策略"].startswith("trend_")]
        return rs[-1] if rs else None
    b = read(base)
    for arm in [base] + arms:
        r = read(arm)
        if not r:
            continue
        d = (float(r["年化"]) - float(b["年化"])) if b else float("nan")
        print(f"  {arm:<10}{float(r['年化'])*100:>7.2f}{float(r['最大回撤'])*100:>9.1f}{float(r['滚动5年年化中位'])*100:>8.2f}"
              f"{float(r['年均换手']):>6.2f}{float(r['平均仓位'])*100:>6.0f}{f(d,8,2)}", file=out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, required=True, help="bt<起点> 目录，内含 <臂>/ledger.csv 等")
    ap.add_argument("--base", default="BASE")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    arms = sorted(d.name for d in args.exp.iterdir() if d.is_dir() and d.name != args.base and (d / "ledger.csv").exists())
    base_rows = read_ledger(args.exp / args.base / "ledger.csv")
    codes = {r["security_code"] for r in base_rows}
    for arm in arms:
        for r in read_ledger(args.exp / arm / "ledger.csv"):
            codes.add(r["security_code"])
        p = args.exp / arm / "blocked.csv"
        if p.exists():
            for r in read_ledger(p):
                codes.add(r["source_code"]); codes.add(r["trigger_code"])
    for e in swap_sells(base_rows):
        codes.add(e["target"])
    names = {}
    for r in base_rows:
        if r.get("security_name"):
            names[r["security_code"]] = r["security_name"]
    mk = Market(codes)
    out = args.out.open("w", encoding="utf-8") if args.out else sys.stdout
    print(f"换仓弱势形态复核·交易细节复盘｜{args.exp}｜臂 {', '.join(arms)}｜涉及代码 {len(codes)}", file=out)
    section_a(mk, base_rows, out)
    section_b(mk, args.exp, arms, out)
    section_c(args.exp, args.base, arms, base_rows, names, out)
    section_d(args.exp, args.base, arms, out)
    if args.out:
        out.close()
        print(f"→ {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
