#!/usr/bin/env python3
"""单旋钮剂量扫描的平台读法（§12.1 第 2 款双门槛 ＋ 第 5 款宽平台优先）。

对每条臂给主读数（滚 5 中位）与复利读数（全期 CAGR）的配对差中位与正号数，
标出双门槛通过的臂，再找**相邻档连续通过**的最长区间——第 5 款要平台不要单点峰。
±0.15pp 内按噪声处理：与 BASE 同在噪声带内的档不算「更好」，只算「不更差」。

用法：scan_plateau.py <sweep 文件> --flag --swap-margin --scale 0.01
"""
import argparse, statistics as st, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sweep_backtest_configs import FIELDS, DEFAULT_STARTS, STANDARD_SET  # noqa: E402

NOISE = 0.0015          # §12.1 第 5 款：±0.15pp
GATES = (("滚5中位", "滚动5年年化中位"), ("年化", "年化"))


def load(path: Path):
    groups = {"": {}, "EX5:": {}}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        p = line.split("|")
        if len(p) != 2 + len(FIELDS):
            continue
        g = "EX5:" if p[0].startswith("EX5:") else ""
        groups[g].setdefault(p[0][len(g):], {})[p[1]] = dict(zip(FIELDS, map(float, p[2:])))
    return groups


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--label", required=True, help="旋钮名，用于表头")
    ap.add_argument("--current", type=float, required=True, help="在册值（BASE 所在档）")
    ap.add_argument("--scale", type=float, default=100.0, help="臂名数字 ÷ scale = 旋钮值")
    args = ap.parse_args()

    groups = load(args.path)
    for gtag, gname in (("", "全样本"), ("EX5:", "去赢家 A")):
        arms = groups[gtag]
        if "BASE" not in arms:
            continue
        base = arms["BASE"]
        starts = [s for s in DEFAULT_STARTS if s in base]
        rows = []
        for label, arm in arms.items():
            val = args.current if label == "BASE" else int(label[2:]) / args.scale
            common = [s for s in starts if s in arm]
            cell = {}
            for nm, k in GATES:
                d = [(arm[s][k] - base[s][k]) * 100 for s in common]
                cell[nm] = (st.median(d), sum(1 for v in d if v > 0), len(d))
            lv = {nm: st.median([arm[s][k] for s in common]) * (100 if sc == 100 else 1)
                  for nm, k, sc, *_ in STANDARD_SET}
            rows.append((val, label, cell, lv, len(common)))
        rows.sort()

        print(f"\n{'='*104}\n【{gname}】{args.label} 剂量扫描（对照＝BASE @ {args.current}）\n{'='*104}")
        print(f"{args.label:<10}{'臂':<8}{'Δ滚5中位':>10}{'符号':>7}{'Δ年化':>9}{'符号':>7}"
              f"{'滚5中位':>9}{'滚5P25':>8}{'滚5回撤':>8}{'年化':>8}{'最大回撤':>9}{'Calmar':>8}{'Sharpe':>8}{'换手':>7}  双门槛")
        ok = {}
        for val, label, cell, lv, n in rows:
            d5, n5, _ = cell["滚5中位"]
            dcg, ncg, _ = cell["年化"]
            passed = label == "BASE" or (d5 >= -NOISE * 100 and dcg >= -NOISE * 100)
            ok[val] = passed
            mark = "—" if label == "BASE" else ("✓" if passed else "✗ 主/复利为负")
            print(f"{val:<10.4g}{label:<8}{d5:>+10.2f}{f'{n5}/{n}':>7}{dcg:>+9.2f}{f'{ncg}/{n}':>7}"
                  f"{lv['滚5中位']:>9.2f}{lv['滚5P25']:>8.2f}{lv['滚5回撤']:>8.1f}{lv['年化']:>8.2f}"
                  f"{lv['最大回撤']:>9.1f}{lv['Calmar']:>8.2f}{lv['Sharpe']:>8.2f}{lv['换手']:>7.2f}  {mark}")
        # 最长连续通过区间
        vals = [v for v, *_ in rows]
        best, cur = [], []
        for v in vals:
            cur = cur + [v] if ok[v] else []
            if len(cur) > len(best):
                best = list(cur)
        print(f"  → 双门槛连续通过的最宽平台：{best[0]:g}~{best[-1]:g}（{len(best)} 档）" if best
              else "  → 无连续通过区间")


if __name__ == "__main__":
    main()
