#!/usr/bin/env python3
"""把 `ex_winner_symmetry.py`／`ex_winner_dose.py` 的读数文件汇总成 §12.1 第 4 款的表（剔除集 A／B／U 或 K1／K3／K5／K10 各一行）。

每个剔除集下，候选臂对同集 `BASE` 的逐起点配对差：主读数（滚 5 中位）、复利读数（全期 CAGR）、坏情形（滚 5 P25）、
滚 5 回撤中位；报中位（pp）与变好的起点数（回撤以「更浅」计）。另按第 4 款列出标准指标集里配对差中位 < −0.15pp 的项。

用法：ex_winner_symmetry_report.py <sweep_u_文件> --challenger GE_TROUGHOFF
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sweep_backtest_configs import FIELDS  # noqa: E402

DECISION = (("Δ主(滚5中位)", "滚动5年年化中位", 100, +1), ("Δ复利(年化)", "年化", 100, +1),
            ("Δ滚5P25", "滚动5年年化P25", 100, +1), ("Δ滚5回撤", "滚动5年回撤中位", 100, -1))
# 第 4 款「不劣」判定的标准指标集（换手、仓位、长跑锚点不计入）
CLAUSE4 = (("滚动5年年化中位", 100, +1), ("滚动5年年化P25", 100, +1), ("滚动5年年化最差", 100, +1),
           ("滚动5年回撤中位", 100, -1), ("滚动5年Calmar中位", 1, +1), ("滚动5年Sharpe中位", 1, +1),
           ("滚动5年为负的窗口占比", 100, -1), ("年化", 100, +1), ("最大回撤", 100, -1), ("Calmar", 1, +1),
           ("Sharpe", 1, +1), ("互不重叠5年块中位", 100, +1), ("滚动3年年化中位", 100, +1),
           ("滚动3年回撤中位", 100, -1), ("逐年收益中位", 100, +1), ("逐年最差", 100, +1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep", type=Path)
    ap.add_argument("--challenger", required=True)
    args = ap.parse_args()
    sets, rows = {}, {}          # rows[(set, label)][since] = {field: value}
    for line in args.sweep.read_text(encoding="utf-8").splitlines():
        if line.startswith("#SET|"):
            _, tag, codes = line.split("|", 2)
            sets[tag] = codes
            continue
        parts = line.split("|")
        if len(parts) < 3 or not parts[0].startswith("EX5:"):
            continue
        full = parts[0][4:]
        # 集合标签可多字符（对称性 A/B/U、剂量 K1/K3/K5/K10）：取能与 `#SET` 行匹配的最长前缀
        tag = max((t for t in sets if full.startswith(t)), key=len, default=None)
        if tag is None or parts[2] in ("ERR", "EMPTY"):
            continue
        label = full[len(tag):]
        rows.setdefault((tag, label), {})[parts[1]] = dict(zip(FIELDS, map(float, parts[2:])))
    print(f"候选 {args.challenger}；剔除集：" + "；".join(f"{t} = {c.replace(',', '/')}" for t, c in sets.items()))
    print("| 剔除集 | " + " | ".join(n for n, *_ in DECISION) + " | 第 4 款劣于 −0.15pp 的项 |")
    print("| --- | " + " | ".join("---:" for _ in DECISION) + " | --- |")
    for tag in sets:
        base, arm = rows.get((tag, "BASE"), {}), rows.get((tag, args.challenger), {})
        starts = sorted(set(base) & set(arm))
        cells = []
        for name, key, scale, good in DECISION:
            d = [(arm[s][key] - base[s][key]) * scale for s in starts]
            better = sum(1 for x in d if x * good > 0)
            cells.append(f"{statistics.median(d):+.2f}（{better}/{len(d)}{' 更浅' if good < 0 else ''}）")
        bad = []
        for key, scale, good in CLAUSE4:
            d = statistics.median((arm[s][key] - base[s][key]) * scale * good for s in starts)
            if d < -0.15:
                bad.append(f"{key} {d:+.2f}")
        print(f"| {tag}（{len(sets[tag].split(','))} 只） | " + " | ".join(cells) + f" | {'、'.join(bad) or '无'} |")


if __name__ == "__main__":
    main()
