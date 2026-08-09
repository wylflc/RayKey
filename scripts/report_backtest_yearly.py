#!/usr/bin/env python3
"""按自然年拆解回测净值曲线（用户 2026-08-09 指令）。

年化与全程最大回撤都是**跨周期的汇总量**，看不出「哪一年赚哪一年亏、哪一年难熬」。
本脚本从 `*_equity.csv` 逐年拆：年内收益率、**年内最大回撤**（只在该自然年内取峰谷，
不跨年）、年末仓位与持仓只数，并对照沪深300同期。

年内回撤刻意不跨年：跨年计算会把上年的高点带进来，使某一年凭空背上前一年的跌幅。

用法::

    python3 scripts/report_backtest_yearly.py <label>
    python3 scripts/report_backtest_yearly.py trend_x0.5_..._BEST2010 --benchmark
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data/processed/backtest"
INDEX = ROOT / "data/raw/ohlcv/INDEX_000300.csv"


def load_curve(path: Path):
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append((row["date"], float(row["total_equity"]),
                         float(row.get("cash_ratio") or 0), int(float(row.get("positions") or 0))))
    return rows


def load_index():
    if not INDEX.exists():
        return {}
    out = {}
    with INDEX.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                out[row["date"]] = float(row["close"])
            except (KeyError, TypeError, ValueError):
                continue
    return out


def yearly(rows, index):
    by_year = defaultdict(list)
    for day, equity, cash, n in rows:
        by_year[day[:4]].append((day, equity, cash, n))
    prev_equity = None
    prev_index = None
    out = []
    for year in sorted(by_year):
        series = by_year[year]
        start = prev_equity if prev_equity is not None else series[0][1]
        end = series[-1][1]
        peak, drawdown = start, 0.0
        for _d, equity, _c, _n in series:
            peak = max(peak, equity)
            if peak > 0:
                drawdown = max(drawdown, 1 - equity / peak)
        bench = None
        if index:
            days = [d for d, *_ in series if d in index]
            if days:
                base = prev_index if prev_index is not None else index[days[0]]
                bench = index[days[-1]] / base - 1 if base else None
                prev_index = index[days[-1]]
        out.append({"year": year, "ret": end / start - 1 if start else 0.0, "dd": drawdown,
                    "end_equity": end, "cash": series[-1][2], "positions": series[-1][3],
                    "days": len(series), "bench": bench})
        prev_equity = end
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="按自然年拆解回测净值")
    ap.add_argument("label", help="回测标签，或 *_equity.csv 的路径")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    path = Path(args.label)
    if not path.exists():
        path = args.out_dir / f"{args.label}_equity.csv"
    if not path.exists():
        hits = sorted(args.out_dir.glob(f"*{args.label}*_equity.csv"))
        if not hits:
            print(f"**找不到净值文件**：{args.label}")
            return 1
        path = hits[0]

    rows = load_curve(path)
    stats = yearly(rows, load_index())
    print(f"{path.name}｜{rows[0][0]} ~ {rows[-1][0]}｜{len(rows):,} 个交易日")
    print(f'\n{"年份":<6}{"当年收益":>10}{"年内最大回撤":>13}{"沪深300":>10}{"超额":>9}'
          f'{"年末资产(万)":>13}{"年末持仓":>8}{"年末现金":>9}')
    print("-" * 80)
    for s in stats:
        bench = f"{s['bench']:>9.1%}" if s["bench"] is not None else f'{"-":>9}'
        excess = f"{s['ret'] - s['bench']:>8.1%}" if s["bench"] is not None else f'{"-":>8}'
        print(f'{s["year"]:<6}{s["ret"]:>10.2%}{s["dd"]:>13.1%}{bench}{excess}'
              f'{s["end_equity"] / 1e4:>13,.0f}{s["positions"]:>8}{s["cash"]:>9.1%}')
    wins = [s for s in stats if s["ret"] > 0]
    beat = [s for s in stats if s["bench"] is not None and s["ret"] > s["bench"]]
    worst = min(stats, key=lambda s: s["ret"])
    deep = max(stats, key=lambda s: s["dd"])
    print("-" * 80)
    print(f'{"合计":<6}{len(stats)} 个自然年｜盈利 {len(wins)} 年（{len(wins)/len(stats):.0%}）'
          f'｜跑赢沪深300 {len(beat)} 年（{len(beat)/len(stats):.0%}）')
    print(f'      最差年份 {worst["year"]}（{worst["ret"]:.2%}）｜年内回撤最深 {deep["year"]}（{deep["dd"]:.1%}）')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
