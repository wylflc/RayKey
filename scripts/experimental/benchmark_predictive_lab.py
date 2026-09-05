#!/usr/bin/env python3
"""比较基准的前沿预测力检验（OI-122，用户 2026-09-01 指令：选出最能反映策略未来真实年化的比较基准）。

在同一批逐日净值曲线上，站在每个历史月末 T、只用 T 及之前的数据计算各候选口径的读数 E(≤T)，
对照同一条曲线其后 (T, T+5年] 的**真实实现年化** F5(T)，量三件事：

1. **水平腿**——E(≤T) 作为 F5(T) 的点预测：偏差（均值 E−F5）、MAE、RMSE、Spearman；
   另给按截止年分组的偏差剖面（预测误差随行情段翻转的形态）。
2. **Δ 腿**——臂对 `BASE` 的逐细胞配对差 ΔE(≤T) 预测 ΔF5(T)：符号一致率、Spearman、MAE(pp)，
   参照行给零预测器（恒 Δ=0）的 MAE 下限 `|ΔF5|均值`。
3. **家族排序腿**——每个细胞上全部臂按 E 排序 vs 按 F5 排序的 Spearman（臂间比较基准的直接检验）。

候选口径（全部只用 T 及之前的数据）：全期 CAGR（起点→T）、滚 5 年重叠窗口中位（现行主读数式）、
滚 5 年 P25（引擎式 sorted[n//4]）、互不重叠 5 年块中位（自 T 往回首尾相接）、末端 5 年 CAGR
（T−5年→T，纯近因端）、滚 10 年中位（T ≥ 起点+10 年才有值）。

细胞资格：T 为月末、T ≥ 起点+5 年（滚 5 至少 1 窗）且 T+5 年仍在数据内（F5 存在）。
相邻细胞的未来窗口共享 59/60 个月，细胞不是独立样本；按截止年分组的剖面即为此而设。

用法：
    python3 scripts/experimental/benchmark_predictive_lab.py --exp data/experiments/exp_window_step
目录下每臂一个子目录（`BASE`、`TW000`…），内含各起点的 `*_equity.csv`。
"""
from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "experimental"))
from window_step_lab import load_curve, month_end_indices  # noqa: E402

ESTIMATORS = ("全期CAGR", "滚5重叠中位", "滚5P25", "互不重叠5年块中位", "末端5年CAGR", "滚10中位")


def shift_month(key: str, months: int) -> str:
    y, m = int(key[:4]), int(key[5:7])
    t = y * 12 + (m - 1) + months
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def cagr(curve, j: int, i: int) -> float | None:
    first, last = curve[j][1], curve[i][1]
    if first <= 0 or last <= 0 or i <= j:
        return None
    span = (date.fromisoformat(curve[i][0]) - date.fromisoformat(curve[j][0])).days / 365.25
    return (last / first) ** (1 / span) - 1


def p25(vals: list[float]) -> float:
    g = sorted(vals)
    return g[len(g) // 4]


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda k: v[k])
        r = [0.0] * n
        k = 0
        while k < n:
            j = k
            while j + 1 < n and v[order[j + 1]] == v[order[k]]:
                j += 1
            for t in range(k, j + 1):
                r[order[t]] = (k + j) / 2 + 1
            k = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def frontier_cells(curve) -> dict[str, dict]:
    """逐月末 T 的 {月键: {各估计量, F5, F至末}}；键仅含合格细胞。"""
    ends = month_end_indices(curve)
    by_month = {curve[i][0][:7]: i for i in ends}
    w5: dict[str, float] = {}
    w10: dict[str, float] = {}
    for i in ends:
        mk = curve[i][0][:7]
        for years, box in ((5, w5), (10, w10)):
            j = by_month.get(shift_month(mk, -12 * years))
            if j is not None:
                v = cagr(curve, j, i)
                if v is not None:
                    box[mk] = v
    out: dict[str, dict] = {}
    months = sorted(by_month)
    for mk in months:
        if mk not in w5:
            continue
        i2 = by_month.get(shift_month(mk, 60))
        if i2 is None:
            continue
        i = by_month[mk]
        f5 = cagr(curve, i, i2)
        fend = cagr(curve, i, len(curve) - 1)
        if f5 is None or fend is None:
            continue
        hist5 = [w5[m] for m in months if m in w5 and m <= mk]
        blocks = []
        e = mk
        while e in w5:
            blocks.append(w5[e])
            e = shift_month(e, -60)
        hist10 = [w10[m] for m in months if m in w10 and m <= mk]
        out[mk] = {
            "全期CAGR": cagr(curve, 0, i),
            "滚5重叠中位": statistics.median(hist5),
            "滚5P25": p25(hist5),
            "互不重叠5年块中位": statistics.median(blocks),
            "末端5年CAGR": w5[mk],
            "滚10中位": statistics.median(hist10) if hist10 else None,
            "F5": f5,
            "F至末": fend,
        }
    return out


def fmt(x, n=2, pct=True):
    if x is None:
        return "—"
    return f"{x * 100:+.{n}f}" if pct else f"{x:+.{n}f}"


def level_rows(cells: list[dict], target: str):
    rows = []
    for est in ESTIMATORS:
        pairs = [(c[est], c[target]) for c in cells if c[est] is not None]
        if not pairs:
            rows.append((est, 0, None, None, None, None))
            continue
        errs = [e - f for e, f in pairs]
        bias = statistics.fmean(errs)
        mae = statistics.fmean(abs(v) for v in errs)
        rmse = (statistics.fmean(v * v for v in errs)) ** 0.5
        rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        rows.append((est, len(pairs), bias, mae, rmse, rho))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", type=Path, required=True)
    ap.add_argument("--base", default="BASE")
    ap.add_argument("--arms", default=None, help="逗号分隔；缺省取 --exp 下全部有曲线的子目录")
    args = ap.parse_args()

    arm_names = ([a.strip() for a in args.arms.split(",") if a.strip()] if args.arms
                 else sorted(d.name for d in args.exp.iterdir() if d.is_dir() and list(d.glob("*_equity.csv"))))
    if args.base not in arm_names:
        sys.exit(f"缺 {args.base} 曲线")
    arm_names = [args.base] + [a for a in arm_names if a != args.base]

    cells: dict[str, dict[str, dict[str, dict]]] = {}   # arm -> start -> 月键 -> 细胞
    for arm in arm_names:
        cells[arm] = {}
        for path in sorted((args.exp / arm).glob("*_equity.csv")):
            digits = "".join(c for c in path.name.split("_")[-2] if c.isdigit())[-8:]
            if len(digits) != 8:
                continue
            start = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
            cells[arm][start] = frontier_cells(load_curve(path))
    starts = sorted(set.intersection(*(set(cells[a]) for a in arm_names)))
    ncell = sum(len(cells[args.base][s]) for s in starts)
    print(f"臂 {len(arm_names)} 个（{','.join(arm_names)}）｜共同起点 {len(starts)} 个｜"
          f"{args.base} 合格细胞 (起点,T) {ncell} 个")

    # ---- 【A】水平腿 ----
    for arm in arm_names:
        flat = [c for s in starts for c in cells[arm][s].values()]
        print(f"\n【A】水平腿｜{arm}：E(≤T) 预测 F5(T)（细胞 = 起点×月末 T，相邻未来窗共享 59/60 个月）")
        print(f"  {'估计量':<18}{'细胞数':>7}{'偏差E−F5':>10}{'MAE':>8}{'RMSE':>8}{'Spearman':>9}"
              f"{'│ 对F至末:偏差':>14}{'MAE':>8}")
        rows5 = level_rows(flat, "F5")
        rowsE = {r[0]: r for r in level_rows(flat, "F至末")}
        for est, n, bias, mae, rmse, rho in rows5:
            e2 = rowsE[est]
            print(f"  {est:<18}{n:>7}{fmt(bias):>10}{fmt(mae):>8}{fmt(rmse):>8}"
                  f"{fmt(rho, 2, pct=False):>9}{fmt(e2[2]):>14}{fmt(e2[3]):>8}")

    # ---- 【A2】BASE 偏差按截止年 ----
    flat_by_year: dict[str, list[dict]] = defaultdict(list)
    for s in starts:
        for mk, c in cells[args.base][s].items():
            flat_by_year[mk[:4]].append(c)
    years = sorted(flat_by_year)
    print(f"\n【A2】{args.base} 偏差（均值 E−F5，pp）按截止年：预测误差随行情段的翻转形态")
    print("  " + f"{'估计量':<18}" + "".join(f"{y:>9}" for y in years))
    for est in ESTIMATORS:
        row = []
        for y in years:
            errs = [c[est] - c["F5"] for c in flat_by_year[y] if c[est] is not None]
            row.append(fmt(statistics.fmean(errs)) if errs else "—")
        print("  " + f"{est:<18}" + "".join(f"{v:>9}" for v in row))
    print("  " + f"{'细胞数':<18}" + "".join(f"{len(flat_by_year[y]):>9}" for y in years))

    others = [a for a in arm_names if a != args.base]
    if not others:
        return

    # ---- 【B】Δ 腿 ----
    print(f"\n【B】Δ 腿｜臂对 {args.base} 的 ΔE(≤T) 预测 ΔF5(T)（{len(others)} 对臂合并）")
    print(f"  {'估计量':<18}{'细胞数':>7}{'符号一致':>9}{'Spearman':>9}{'MAE(pp)':>9}")
    dref = []
    for est in ESTIMATORS + ("零预测器",):
        de, df = [], []
        for arm in others:
            for s in starts:
                for mk, c in cells[arm][s].items():
                    b = cells[args.base][s].get(mk)
                    if b is None or c["F5"] is None:
                        continue
                    if est == "零预测器":
                        de.append(0.0)
                        df.append(c["F5"] - b["F5"])
                        continue
                    if c[est] is None or b[est] is None:
                        continue
                    de.append(c[est] - b[est])
                    df.append(c["F5"] - b["F5"])
        if not de:
            continue
        if est == "零预测器":
            mae = statistics.fmean(abs(f) for f in df)
            print(f"  {est:<18}{len(de):>7}{'—':>9}{'—':>9}{mae * 100:>9.2f}")
            continue
        agree = sum(1 for a, b in zip(de, df) if a * b > 0) / len(de)
        rho = spearman(de, df)
        mae = statistics.fmean(abs(a - b) for a, b in zip(de, df))
        print(f"  {est:<18}{len(de):>7}{agree * 100:>8.1f}%{fmt(rho, 2, pct=False):>9}{mae * 100:>9.2f}")
        dref.append(est)

    print(f"\n  逐对臂的符号一致率（%）：")
    print("  " + f"{'估计量':<18}" + "".join(f"{a:>8}" for a in others))
    for est in ESTIMATORS:
        row = []
        for arm in others:
            de, df = [], []
            for s in starts:
                for mk, c in cells[arm][s].items():
                    b = cells[args.base][s].get(mk)
                    if b is None or c[est] is None or b[est] is None:
                        continue
                    de.append(c[est] - b[est])
                    df.append(c["F5"] - b["F5"])
            row.append(f"{sum(1 for a, b in zip(de, df) if a * b > 0) / len(de) * 100:.0f}" if de else "—")
        print("  " + f"{est:<18}" + "".join(f"{v:>8}" for v in row))

    print(f"\n  符号一致率（%）按截止年（{len(others)} 对臂合并；晚年 = 前沿历史更长、更接近生产语境）：")
    print("  " + f"{'估计量':<18}" + "".join(f"{y:>8}" for y in years))
    for est in ESTIMATORS:
        by_year_pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for arm in others:
            for s in starts:
                for mk, c in cells[arm][s].items():
                    b = cells[args.base][s].get(mk)
                    if b is None or c[est] is None or b[est] is None:
                        continue
                    by_year_pairs[mk[:4]].append((c[est] - b[est], c["F5"] - b["F5"]))
        row = []
        for y in years:
            ps = by_year_pairs[y]
            row.append(f"{sum(1 for a, b in ps if a * b > 0) / len(ps) * 100:.0f}" if ps else "—")
        print("  " + f"{est:<18}" + "".join(f"{v:>8}" for v in row))

    # ---- 【C】家族排序腿 ----
    print(f"\n【C】家族排序腿｜每细胞 {len(arm_names)} 臂按 E 排 vs 按 F5 排的 Spearman（均值｜按截止年）")
    print("  " + f"{'估计量':<18}{'细胞数':>7}{'均值ρ':>8}" + "".join(f"{y:>8}" for y in years))
    for est in ESTIMATORS:
        rhos_by_year: dict[str, list[float]] = defaultdict(list)
        for s in starts:
            for mk in cells[args.base][s]:
                es, fs = [], []
                for arm in arm_names:
                    c = cells[arm][s].get(mk)
                    if c is None or c[est] is None:
                        break
                    es.append(c[est])
                    fs.append(c["F5"])
                else:
                    r = spearman(es, fs)
                    if r is not None:
                        rhos_by_year[mk[:4]].append(r)
        allr = [r for v in rhos_by_year.values() for r in v]
        if not allr:
            print("  " + f"{est:<18}{'—':>7}")
            continue
        row = "".join(f"{fmt(statistics.fmean(rhos_by_year[y]), 2, pct=False) if rhos_by_year[y] else '—':>8}"
                      for y in years)
        print("  " + f"{est:<18}{len(allr):>7}{fmt(statistics.fmean(allr), 2, pct=False):>8}" + row)


if __name__ == "__main__":
    main()
