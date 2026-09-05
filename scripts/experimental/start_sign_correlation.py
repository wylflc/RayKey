#!/usr/bin/env python3
"""OI-119：14 个标准起点上「正号起点数」的证据强度实测（回测日志 §12.169）。

读 `data/backtest/scan_summaries.csv`，把扫描标签按「臂名＋起点日」拆开，取 14 个标准起点齐全的臂，
随机抽臂对算逐起点配对差（年化），报：起点间相关矩阵的平均相关与有效样本量（Kish 与特征值两种）、
按 |配对差中位| 分桶的「≥11/14 同号」「14/14 同号」出现率，以及二项分布参照。

Run: ``python3 scripts/experimental/start_sign_correlation.py [--pairs 40000] [--key 年化]``
"""
from __future__ import annotations

import argparse
import collections
import csv
import itertools
import random
import re
import statistics
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUMMARIES = ROOT / "data/backtest/scan_summaries.csv"
STD_STARTS = ["20091101", "20100501", "20101101", "20110501", "20111101", "20120501", "20121101",
              "20130501", "20131101", "20140501", "20141101", "20150501", "20151101", "20160501"]
LABEL = re.compile(r"^(.*?)(\d{8})$")


def _corr(x: list[float], y: list[float]) -> float:
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = sum((a - mx) ** 2 for a in x) ** 0.5
    sy = sum((b - my) ** 2 for b in y) ** 0.5
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", type=int, default=40000)
    ap.add_argument("--key", default="年化", help="用哪条读数算配对差（缺省复利读数）")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    fam: dict[str, dict[str, float]] = collections.defaultdict(dict)
    with SUMMARIES.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            m = LABEL.match(row["扫描标签"])
            if not m:
                continue
            try:
                fam[m.group(1)][m.group(2)] = float(row[args.key])
            except (TypeError, ValueError):
                continue
    full = {k: [d[s] for s in STD_STARTS] for k, d in fam.items() if all(s in d for s in STD_STARTS)}
    n = len(STD_STARTS)
    print(f"14 起点齐全的臂 {len(full)}／{len(fam)}；读数 {args.key}")
    keys = sorted(full)
    pairs = list(itertools.combinations(keys, 2))
    random.Random(args.seed).shuffle(pairs)
    pairs = pairs[:args.pairs]
    deltas = [[full[a][i] - full[b][i] for i in range(n)] for a, b in pairs]
    cols = [[d[i] for d in deltas] for i in range(n)]
    corr = [[_corr(cols[i], cols[j]) for j in range(n)] for i in range(n)]
    rho = statistics.mean(corr[i][j] for i in range(n) for j in range(n) if i != j)
    kish = n / (1 + (n - 1) * rho)
    try:
        import numpy as np
        lam = np.linalg.eigvalsh(np.array(corr))
        eig = float(lam.sum() ** 2 / (lam ** 2).sum())
    except ImportError:
        eig = float("nan")
    print(f"臂对 {len(deltas)}；起点间平均相关 {rho:.3f}；有效样本量 Kish {kish:.2f}、特征值 {eig:.2f}；"
          f"相邻起点相关 {statistics.mean(corr[i][i + 1] for i in range(n - 1)):.3f}、"
          f"相隔 5 年 {statistics.mean(corr[i][i + 10] for i in range(n - 10)):.3f}")

    def max_sign(d: list[float]) -> int:
        return max(sum(1 for x in d if x > 0), sum(1 for x in d if x < 0))

    print(f"{'|配对差中位| 桶(pp)':<20}{'臂对数':>8}{'≥11/14 同号':>12}{'≥12/14':>8}{'14/14':>8}")
    for lo, hi in ((0, 0.15), (0.15, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 5.0), (5.0, 1e9)):
        sub = [d for d in deltas if lo <= abs(statistics.median(d)) * 100 < hi]
        if not sub:
            continue
        c = collections.Counter(max_sign(d) for d in sub)
        share = lambda k: sum(v for kk, v in c.items() if kk >= k) / len(sub)
        print(f"[{lo:g}, {hi if hi < 1e9 else '∞'}){'':<11}{len(sub):>8}{share(11):>12.2f}{share(12):>8.2f}{share(14):>8.2f}")
    print(f"二项分布 p=0.5 参照：P(≥11/14)={sum(comb(n, k) for k in range(11, n + 1)) / 2 ** n:.3f}、"
          f"P(≥12/14)={sum(comb(n, k) for k in range(12, n + 1)) / 2 ** n:.3f}、P(14/14)={1 / 2 ** n:.4f}")
    given = [abs(statistics.median(d)) * 100 for d in deltas if max_sign(d) >= 11]
    given.sort()
    q = lambda p: given[int(p * (len(given) - 1))] if given else float("nan")
    print(f"给定 ≥11/14 同号：|配对差中位| P10／P25／中位 = {q(0.1):.2f}／{q(0.25):.2f}／{q(0.5):.2f} pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
