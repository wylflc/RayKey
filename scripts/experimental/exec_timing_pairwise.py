#!/usr/bin/env python3
"""执行时点四臂的任意两臂逐起点配对差（§12.1 第 3 款口径：配对差中位与正号起点数）。

读 `sweep_backtest_configs.py` 的扫描文件（首行 #METRIC），对给定的 (臂A, 臂B) 对，
按起点配对报 A − B 的中位与 A 更高的起点数；全样本与去赢家（EX5: 前缀）两表各出一份。
用法：python3 scripts/experimental/exec_timing_pairwise.py <sweep.txt> A:B [A:B ...]
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

KEYS = ("年化", "滚动5年年化中位", "滚动5年年化P25", "滚动5年年化最差", "滚动5年回撤中位",
        "最大回撤", "Sharpe", "滚动5年Sharpe中位", "互不重叠5年块中位", "逐年收益中位", "逐年最差",
        "年均换手", "平均仓位", "最低担保比例")
PCT = {"年化", "滚动5年年化中位", "滚动5年年化P25", "滚动5年年化最差", "滚动5年回撤中位", "最大回撤",
       "互不重叠5年块中位", "逐年收益中位", "逐年最差"}


def load(path: Path):
    fields, rows = None, {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#METRIC|"):
            fields = line.split("|", 2)[2].split(",")
            continue
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) != 2 + len(fields) or parts[2] in ("ERR", "EMPTY"):
            continue
        label, since = parts[0], parts[1]
        table = "去赢家" if label.startswith("EX5:") else "全样本"
        rows[(table, label.removeprefix("EX5:"), since)] = dict(zip(fields, map(float, parts[2:])))
    return rows


def main() -> None:
    rows = load(Path(sys.argv[1]))
    pairs = [p.split(":") for p in sys.argv[2:]]
    for table in ("全样本", "去赢家"):
        print(f"\n【{table}】A − B 逐起点配对差：中位（pp 或比率）／A 更高的起点数／起点数")
        head = f"{'A:B':<12}" + "".join(f"{k:>16}" for k in KEYS)
        print(head)
        for a, b in pairs:
            starts = sorted({s for t, l, s in rows if t == table and l == a}
                            & {s for t, l, s in rows if t == table and l == b})
            if not starts:
                print(f"{a}:{b:<8} 无配对起点")
                continue
            cells = []
            for k in KEYS:
                d = [rows[(table, a, s)][k] - rows[(table, b, s)][k] for s in starts]
                med = statistics.median(d)
                pos = sum(1 for v in d if v > 0)
                cells.append(f"{med * (100 if k in PCT else 1):+8.2f} {pos:>2}/{len(d):<2}")
            print(f"{a}:{b:<8}" + "".join(f"{c:>16}" for c in cells))
        # 水平中位（只描述）
        print(f"{'水平中位':<12}" + "".join(f"{k:>16}" for k in KEYS))
        for arm in sorted({l for t, l, s in rows if t == table}):
            vals = [rows[(t, l, s)] for t, l, s in rows if t == table and l == arm]
            print(f"{arm:<12}" + "".join(
                f"{statistics.median(v[k] for v in vals) * (100 if k in PCT else 1):>16.2f}" for k in KEYS))


if __name__ == "__main__":
    main()
