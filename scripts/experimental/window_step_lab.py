#!/usr/bin/env python3
"""窗口口径的敏感度实验（用户 2026-09-01 提问）：同一批逐日净值上重算不同的收益读数，
看 §12.1 第 2 款的结论对「滚动窗长／推进步长／起点集」有多敏感。**不改任何交易规则。**

问的三件事：

1. **步长**——滚 5 年现按每个月末锚定（步长 1 个月，每起点约 140 个窗口）。改成半年一格
   会不会让读数更干净？本表给步长 1／3／6／12 个月的同一读数。
   注意窗口**重叠比例由窗长决定、与步长无关**：相邻两个月末窗共享 59/60 的样本期，
   相邻两个半年窗共享 54/60。稀化只减少观测数，不减少重叠。
2. **窗长**——同表给滚 10 年与**互不重叠 5 年块**（同一起点内首尾相接、零重叠）。
3. **起点集**——23 个半年起点共享同一个终点，故越靠近终点的日历期出现在越多起点里。
   本表按起点集 23／5／3 个分别重算，并印出逐年的「被多少个起点覆盖」权重剖面。

用法：
    python3 scripts/experimental/window_step_lab.py --exp data/experiments/exp_window_step
目录下每臂一个子目录，内含各起点的 `*_equity.csv`（回测不带 --no-artifacts 时落）。
"""
from __future__ import annotations

import argparse
import calendar
import csv
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import sweep_backtest_configs as sweep  # noqa: E402

STEPS = (1, 3, 6, 12)


def load_curve(path: Path) -> list[tuple[str, float]]:
    out = []
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                out.append((r["date"], float(r["net_equity"])))
            except (TypeError, ValueError):
                pass
    return out


def month_end_indices(curve) -> list[int]:
    """与引擎 `month_end_indices` 同式：每个自然月最后一个交易日；截断处的残月不算。"""
    idx = [i for i in range(len(curve) - 1) if curve[i][0][:7] != curve[i + 1][0][:7]]
    if curve:
        last = date.fromisoformat(curve[-1][0])
        dim = calendar.monthrange(last.year, last.month)[1]
        if all(date(last.year, last.month, d).weekday() >= 5 for d in range(last.day + 1, dim + 1)):
            idx.append(len(curve) - 1)
    return idx


def rolling_cagrs(curve, years: int, step: int) -> list[float]:
    """滚动 `years` 年窗口的 CAGR，窗口末日取每第 `step` 个月末（step=1 即引擎口径）。"""
    ends = month_end_indices(curve)
    by_month = {curve[i][0][:7]: i for i in ends}
    out = []
    for k, i in enumerate(ends):
        if (len(ends) - 1 - k) % step:          # 自最新月末往回数，保证终点总在样本里
            continue
        end_day = curve[i][0]
        y, m = int(end_day[:4]), int(end_day[5:7])
        j = by_month.get(f"{y - years:04d}-{m:02d}")
        if j is None:
            continue
        first, last = curve[j][1], curve[i][1]
        if first <= 0 or last <= 0:
            continue
        span = (date.fromisoformat(end_day) - date.fromisoformat(curve[j][0])).days / 365.25
        out.append((last / first) ** (1 / span) - 1)
    return out


def disjoint_cagrs(curve, years: int) -> list[float]:
    """互不重叠的 `years` 年块：自最新月末往回每 `years×12` 个月切一刀，零重叠。"""
    return rolling_cagrs(curve, years, years * 12)


def fmt(x, n=2):
    return "—" if x is None else f"{x * 100:+.{n}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, required=True)
    ap.add_argument("--base", default="BASE")
    ap.add_argument("--arm", default="TW000")
    args = ap.parse_args()

    curves: dict[str, dict[str, list]] = {}
    for arm in (args.base, args.arm):
        curves[arm] = {}
        for path in sorted((args.exp / arm).glob("*_equity.csv")):
            tag = path.name
            digits = "".join(c for c in tag.split("_")[-2] if c.isdigit())[-8:]
            if len(digits) != 8:
                continue
            start = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
            curves[arm][start] = load_curve(path)
    starts = sorted(set(curves[args.base]) & set(curves[args.arm]))
    print(f"起点 {len(starts)} 个｜{args.base} 曲线 {len(curves[args.base])}｜{args.arm} 曲线 {len(curves[args.arm])}")
    if not starts:
        sys.exit("没有可配对的起点曲线")

    # ---- 起点集的日历权重剖面 ----
    print("\n【1】23 个起点共享同一终点 → 日历期的覆盖权重（该年出现在多少个起点的路径里）")
    cover: dict[str, int] = defaultdict(int)
    for s in starts:
        for y in range(int(s[:4]), int(curves[args.base][s][-1][0][:4]) + 1):
            cover[str(y)] += 1
    print("  " + "  ".join(f"{y}:{n}" for y, n in sorted(cover.items())))
    w5: dict[str, int] = defaultdict(int)
    for s in starts:
        for c in rolling_windows_ends(curves[args.base][s], 5):
            w5[c[:4]] += 1
    print("  滚 5 年窗口**末日**落在各年的个数（23 起点合计）：")
    print("  " + "  ".join(f"{y}:{n}" for y, n in sorted(w5.items())))

    # ---- 主表 ----
    variants: list[tuple[str, callable]] = []
    for st in STEPS:
        variants.append((f"滚5·步长{st}月", lambda c, st=st: rolling_cagrs(c, 5, st)))
    variants.append(("滚10·步长1月", lambda c: rolling_cagrs(c, 10, 1)))
    variants.append(("互不重叠5年块", lambda c: disjoint_cagrs(c, 5)))

    for subset, label in ((starts, f"全部 {len(starts)} 起点"),
                          (starts[::6][:5], "稀疏 5 起点"),
                          ([starts[0], starts[len(starts) // 2], starts[-1]], "3 起点")):
        print(f"\n【2】{label}：Δ({args.arm} − {args.base}) 的逐起点配对差")
        print(f"  {'口径':<16}{'窗口数/起点':>12}{'Δ中位(pp)':>11}{'符号':>8}"
              f"{'Δ均值':>9}{'Δ最小':>9}{'Δ最大':>9}{args.base + ' 中位':>12}{args.arm + ' 中位':>12}")
        for name, fn in variants:
            per_start = []
            nwin = []
            lv_b, lv_a = [], []
            for s in subset:
                b, a = fn(curves[args.base][s]), fn(curves[args.arm][s])
                if not b or not a:
                    continue
                nwin.append(len(b))
                mb, ma = statistics.median(b), statistics.median(a)
                lv_b.append(mb)
                lv_a.append(ma)
                per_start.append(ma - mb)
            if not per_start:
                print(f"  {name:<16}{'—':>12}")
                continue
            pos = sum(1 for v in per_start if v > 0)
            print(f"  {name:<16}{statistics.median(nwin):>12.0f}"
                  f"{fmt(statistics.median(per_start)):>11}{f'{pos}/{len(per_start)}':>8}"
                  f"{fmt(statistics.fmean(per_start)):>9}{fmt(min(per_start)):>9}{fmt(max(per_start)):>9}"
                  f"{fmt(statistics.median(lv_b)):>12}{fmt(statistics.median(lv_a)):>12}")


def rolling_windows_ends(curve, years: int) -> list[str]:
    ends = month_end_indices(curve)
    by_month = {curve[i][0][:7]: i for i in ends}
    out = []
    for i in ends:
        y, m = int(curve[i][0][:4]), int(curve[i][0][5:7])
        if by_month.get(f"{y - years:04d}-{m:02d}") is not None:
            out.append(curve[i][0])
    return out


if __name__ == "__main__":
    main()
