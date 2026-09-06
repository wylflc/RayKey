#!/usr/bin/env python3
"""OI-159 H1 读数：策略滚动 5 年 CAGR 中位 − 标普 500 全收益同窗口 CAGR 中位，逐起点配对差（预登记 §1／§5）。

窗口与引擎同式（`backtest_valuation_strategy.rolling_windows`）：月末锚定、60 个月前同月末为首日、按日历年数年化；
指数曲线取 [起点, 该起点末次净值日]。另报全期 CAGR 配对差（策略「年化」列 − 指数同期日历年化）。
用法：
    python3 scripts/experimental/us_h1_readout.py --scan data/experiments/exp_us_sp500_port/scan_us.txt [--arm BASE] [--index data/raw/ohlcv_us/INDEX_SP500TR.csv]
"""
from __future__ import annotations

import argparse
import calendar
import csv
import statistics
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_scan(path: Path, arm: str) -> list[dict]:
    fields = None
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#METRIC|"):
            fields = [n for n in line.split("|", 2)[2].split(",") if n]
            continue
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("|")
        if parts[0] != arm or len(parts) != 2 + len(fields or []):
            continue
        rows.append({"since": parts[1], **dict(zip(fields, map(float, parts[2:])))})
    return sorted(rows, key=lambda r: r["since"])


def month_end_indices(days: list[str]) -> list[int]:
    idx = [i for i in range(len(days) - 1) if days[i][:7] != days[i + 1][:7]]
    if days:
        last = date.fromisoformat(days[-1])
        dim = calendar.monthrange(last.year, last.month)[1]
        if all(date(last.year, last.month, d).weekday() >= 5 for d in range(last.day + 1, dim + 1)):
            idx.append(len(days) - 1)
    return idx


def index_rolling_median(index: list[tuple[str, float]], since: str, until: str, years: int = 5) -> tuple[float | None, int]:
    curve = [(d, v) for d, v in index if since <= d <= until]
    days = [d for d, _ in curve]
    ends = month_end_indices(days)
    by_month = {days[i][:7]: i for i in ends}
    cagrs = []
    for i in ends:
        y, m = int(days[i][:4]), int(days[i][5:7])
        j = by_month.get(f"{y - years:04d}-{m:02d}")
        if j is None:
            continue
        span = (date.fromisoformat(days[i]) - date.fromisoformat(days[j])).days / 365.25
        cagrs.append((curve[i][1] / curve[j][1]) ** (1 / span) - 1)
    return (statistics.median(cagrs) if cagrs else None), len(cagrs)


def full_cagr(index: list[tuple[str, float]], since: str, until: str) -> float | None:
    curve = [(d, v) for d, v in index if since <= d <= until]
    if len(curve) < 2:
        return None
    span = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days / 365.25
    return (curve[-1][1] / curve[0][1]) ** (1 / span) - 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", type=Path, required=True)
    ap.add_argument("--arm", default="BASE")
    ap.add_argument("--index", type=Path, default=ROOT / "data/raw/ohlcv_us/INDEX_SP500TR.csv")
    a = ap.parse_args()
    index = sorted((r["date"], float(r["close"])) for r in csv.DictReader(a.index.open(encoding="utf-8")) if r.get("close"))
    rows = load_scan(a.scan, a.arm)
    if not rows:
        raise SystemExit(f"{a.scan} 里没有臂 {a.arm} 的结果行")
    print(f"H1 读数（臂 {a.arm}，{len(rows)} 个起点；指数 {a.index.name}）")
    print(f"{'起点':10} {'策略滚5中位':>10} {'指数滚5中位':>10} {'配对差pp':>9} {'窗口数':>6} | {'策略全期':>8} {'指数全期':>8} {'配对差pp':>9}")
    d5, dfull = [], []
    for r in rows:
        until = str(int(r["末次净值日"]))
        until = f"{until[:4]}-{until[4:6]}-{until[6:8]}"
        im, n = index_rolling_median(index, r["since"], until)
        ifull = full_cagr(index, r["since"], until)
        s5 = r["滚动5年年化中位"]; sf = r["年化"]
        if im is not None:
            d5.append((s5 - im) * 100)
        if ifull is not None:
            dfull.append((sf - ifull) * 100)
        print(f"{r['since']:10} {s5 * 100:10.2f} {(im or 0) * 100:10.2f} {(s5 - (im or 0)) * 100:9.2f} {n:6d} | {sf * 100:8.2f} {(ifull or 0) * 100:8.2f} {(sf - (ifull or 0)) * 100:9.2f}")
    pos5 = sum(1 for x in d5 if x > 0)
    posf = sum(1 for x in dfull if x > 0)
    print(f"滚 5 配对差中位 {statistics.median(d5):+.2f}pp，正号起点 {pos5}/{len(d5)}；全期配对差中位 {statistics.median(dfull):+.2f}pp，正号起点 {posf}/{len(dfull)}")
    ok = pos5 >= (2 * len(d5) + 2) // 3 and statistics.median(d5) >= 3.0
    print(f"H1（≥ 2/3 起点为正且中位 ≥ +3pp）：{'支持' if ok else '不支持'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
