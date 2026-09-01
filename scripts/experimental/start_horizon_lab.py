#!/usr/bin/env python3
"""起点集路径长度下限的实测（用户 2026-09-02 提问：后面几个起点全被近五年主导，
能否只留路径 ≥ 8 年／≥ 10 年的起点）。与 §12.156 的「稀疏抽起点」不同——本节测的是
**长度下限截断**（保留全部长路径、只去掉短路径），共享终点不变。三张表：

1. **起点集剖面**——各下限下的起点数、路径长、近因权重两种量法：
   路径年数落在 2020 年及以后的占比（复利读数的近因权重，由路径构成决定）与
   滚 5 窗口末日落在 2020 年及以后的占比（滚动读数的近因权重，由共享终点决定、下限动不了）。
2. **家族读数**——§12.155 剂量臂五对 Δ（复利／滚5中位／滚5P25，配对差中位与符号）与
   `BASE` 水平（年化中位／滚5中位／块中位）在 23／≥8年／≥10年 三个起点集下逐一重算；
   全 23 起点列须复现 §12.155 在册值（工具自校验）。
3. **短路径投票剖面**——每臂 Δ复利 在长路径（≥10 年，14 个）与短路径（<10 年，9 个）
   两块里的中位与符号，看短路径是否按同一方向整块投票。

另核验：§12.157 前沿预测力检验的合格细胞（T ≥ 起点+5 年且 T+5 年 ≤ 数据末端）
恰好只落在 ≥10 年的起点上——前沿反向传递的结论本来就是长路径集自己给出的，截断救不了预测力。

用法：
    python3 scripts/experimental/start_horizon_lab.py --exp data/processed/experiments/exp_window_step
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "experimental"))
from window_step_lab import load_curve, rolling_cagrs, disjoint_cagrs, rolling_windows_ends  # noqa: E402

FLOORS = ((None, "全部"), (8.0, "≥8年"), (10.0, "≥10年"))
RECENT = "2020-01-01"


def full_cagr(curve) -> float:
    span = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days / 365.25
    return (curve[-1][1] / curve[0][1]) ** (1 / span) - 1


def path_years(curve) -> float:
    return (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[0][0])).days / 365.25


def recent_years(curve) -> float:
    lo = max(curve[0][0], RECENT)
    if lo > curve[-1][0]:
        return 0.0
    return (date.fromisoformat(curve[-1][0]) - date.fromisoformat(lo)).days / 365.25


def sgn(deltas) -> str:
    return f"{sum(1 for v in deltas if v > 0)}/{len(deltas)}"


def fmt(x, n=2):
    return f"{x * 100:+.{n}f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, required=True)
    ap.add_argument("--base", default="BASE")
    args = ap.parse_args()

    arm_names = sorted(d.name for d in args.exp.iterdir() if d.is_dir() and list(d.glob("*_equity.csv")))
    arm_names = [args.base] + [a for a in arm_names if a != args.base]
    curves: dict[str, dict[str, list]] = {}
    for arm in arm_names:
        curves[arm] = {}
        for path in sorted((args.exp / arm).glob("*_equity.csv")):
            digits = "".join(c for c in path.name.split("_")[-2] if c.isdigit())[-8:]
            if len(digits) != 8:
                continue
            curves[arm][f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"] = load_curve(path)
    starts = sorted(set.intersection(*(set(curves[a]) for a in arm_names)))
    print(f"臂 {len(arm_names)} 个（{','.join(arm_names)}）｜共同起点 {len(starts)} 个")

    plen = {s: path_years(curves[args.base][s]) for s in starts}
    subsets = {label: [s for s in starts if fl is None or plen[s] >= fl] for fl, label in FLOORS}

    # ---- 【1】起点集剖面 ----
    print("\n【1】起点集剖面（近因权重两种量法：复利读数看路径年数构成，滚动读数看窗口末日构成）")
    print(f"  {'起点集':<8}{'起点数':>5}{'路径长(年)':>12}{'路径年数∑':>9}{'其中≥2020':>9}{'占比':>7}"
          f"{'滚5窗口∑':>8}{'末日≥2020':>9}{'占比':>7}{'每起点块数':>10}")
    for _fl, label in FLOORS:
        sub = subsets[label]
        ys = [plen[s] for s in sub]
        tot = sum(ys)
        rec = sum(recent_years(curves[args.base][s]) for s in sub)
        wins = [rolling_windows_ends(curves[args.base][s], 5) for s in sub]
        nwin = sum(len(w) for w in wins)
        nrec = sum(1 for w in wins for e in w if e >= RECENT)
        blks = [len(disjoint_cagrs(curves[args.base][s], 5)) for s in sub]
        print(f"  {label:<8}{len(sub):>5}{f'{min(ys):.1f}~{max(ys):.1f}':>12}{tot:>9.1f}{rec:>9.1f}"
              f"{rec / tot * 100:>6.1f}%{nwin:>8}{nrec:>9}{nrec / nwin * 100:>6.1f}%"
              f"{f'{min(blks)}~{max(blks)}':>10}")

    # ---- 逐起点读数缓存 ----
    per: dict[str, dict[str, dict[str, float]]] = {}   # arm -> start -> 读数
    for arm in arm_names:
        per[arm] = {}
        for s in starts:
            c = curves[arm][s]
            r5 = rolling_cagrs(c, 5, 1)
            per[arm][s] = {
                "复利": full_cagr(c),
                "滚5中位": statistics.median(r5),
                "滚5P25": sorted(r5)[len(r5) // 4],
                "块中位": statistics.median(disjoint_cagrs(c, 5)),
            }

    # ---- 【2】家族读数按起点集 ----
    others = [a for a in arm_names if a != args.base]
    print("\n【2】家族读数（Δ = 臂 − BASE 逐起点配对差中位｜符号；BASE 行为水平中位）")
    hdr = f"  {'臂':<7}"
    for _fl, label in FLOORS:
        hdr += f"{'Δ复利(' + label + ')':>16}{'符号':>7}{'Δ滚5中位':>10}{'符号':>7}{'Δ滚5P25':>9}{'符号':>7}"
    print(hdr)
    for arm in others:
        row = f"  {arm:<7}"
        for _fl, label in FLOORS:
            sub = subsets[label]
            for key in ("复利", "滚5中位", "滚5P25"):
                d = [per[arm][s][key] - per[args.base][s][key] for s in sub]
                w = 16 if key == "复利" else (10 if key == "滚5中位" else 9)
                row += f"{fmt(statistics.median(d)):>{w}}{sgn(d):>7}"
        print(row)
    row = f"  {args.base:<7}"
    for _fl, label in FLOORS:
        sub = subsets[label]
        row += (f"{'年化' + fmt(statistics.median([per[args.base][s]['复利'] for s in sub])):>16}{'':>7}"
                f"{fmt(statistics.median([per[args.base][s]['滚5中位'] for s in sub])):>10}{'':>7}"
                f"{'块' + fmt(statistics.median([per[args.base][s]['块中位'] for s in sub])):>9}{'':>7}")
    print(row + "   （BASE 行：年化中位｜滚5中位｜块中位）")

    # ---- 【3】短路径投票剖面 ----
    long_set = subsets["≥10年"]
    short_set = [s for s in starts if s not in long_set]
    print(f"\n【3】Δ复利 分块（长路径 {len(long_set)} 个 ≥10 年 vs 短路径 {len(short_set)} 个 <10 年）")
    print(f"  {'臂':<7}{'长:Δ中位':>10}{'符号':>7}{'短:Δ中位':>10}{'符号':>7}")
    for arm in others:
        dl = [per[arm][s]["复利"] - per[args.base][s]["复利"] for s in long_set]
        ds = [per[arm][s]["复利"] - per[args.base][s]["复利"] for s in short_set]
        print(f"  {arm:<7}{fmt(statistics.median(dl)):>10}{sgn(dl):>7}{fmt(statistics.median(ds)):>10}{sgn(ds):>7}")

    # ---- 核验：§12.157 前沿细胞只落在 ≥10 年起点上 ----
    frontier = [s for s in starts if rolling_windows_ends(curves[args.base][s], 5)
                and min(rolling_windows_ends(curves[args.base][s], 5)) <= "2021-08-31"]
    ok = set(frontier) == set(long_set)
    print(f"\n核验：§12.157 前沿细胞的起点集 {'==' if ok else '!='} ≥10 年起点集"
          f"（{len(frontier)} vs {len(long_set)}）——前沿反向传递本来就是长路径集自己的读数")


if __name__ == "__main__":
    main()
