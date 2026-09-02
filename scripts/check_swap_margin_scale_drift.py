#!/usr/bin/env python3
"""换仓边际的标度漂移守卫（§9.3.1「换仓」行，OI-114 结案守卫）。

§9.3.1 的换仓判据是一个减法：`持仓侧 P/V − 候选侧 P/V ≥ 边际`。
两个被减项来自两套逐日状态——候选侧 `a_share_daily_states_adopted.csv`（BASE 口径 `V`），
持仓侧 `a_share_daily_states_hold.csv`（`max(BASE, B2)`，`V` 更高故 `P/V` 更低）。
因此这个差值不是任一侧的 `P/V` 差，它比「同一标度下的差」系统性偏小，闸门偏严。

边际本身是在**这个复合量**上按剂量扫描标定出来的，标度差已吸进标定，故不构成错误。
真正的风险是**漂移**：两套 `V` 的差距一旦变化（换估值方法、口径调整、某类股票重建带），
复合量的分布跟着动，已标定的边际实际严格度**无声改变**。本脚本把那件事变成可见的数字。

口径：对面板在册、且**持仓侧 `P/V` 落在换仓源实测操作区间**的观测，
量 `g = 候选侧 P/V − 持仓侧 P/V`（恒 ≥ 0）。操作区间取实测换仓源的 P5~P95。

**守的是均值不是中位**：八成观测上两侧同值（`max(BASE,B2)` 取到 BASE），中位恒为 0、守不住任何东西；
`g` 的均值才直接等于闸门被低估的幅度——边际 `m` 的实际严格度 ≈ 同标度下的 `m + mean(g)`。
均值漂移超过 `TOLERANCE` 即提示按 §12 重扫换仓边际；不自动改任何参数。

用法：
    python3 scripts/check_swap_margin_scale_drift.py             # 对基准校验，漂移超限时退出码 1
    python3 scripts/check_swap_margin_scale_drift.py --baseline  # 只报当前值（重定基准时用）
"""
from __future__ import annotations

import argparse
import bisect
import csv
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAND_STATES = ROOT / "data/processed/a_share_daily_states_adopted.csv"
HOLD_STATES = ROOT / "data/processed/a_share_daily_states_hold.csv"
PANEL = ROOT / "data/processed/pit_attention/panel_moat_bank_v6b.csv"

# 换仓源实测操作区间（BASE 2011-11 长跑 296 笔换仓卖出的持仓侧 P/V，P5~P95）。
SOURCE_PV_LO, SOURCE_PV_HI = 0.50, 1.11

# 在册基准。重定基准须同时改本行与 §6.7 的守卫步。
MARGIN = 0.15                   # 在册换仓边际，与 SEC93_SWAP_MARGIN／BASE --swap-margin 同值
BASELINE_MEAN_GAP = 0.0164      # 均值：边际的实际严格度 ≈ 同标度下 MARGIN + 本值
BASELINE_NONZERO_SHARE = 0.175  # 有差观测占比，作辅助描述、不触发
TOLERANCE = 0.01                # 均值漂移超此值即提示重扫；≈ 0.18~0.20 平台半宽


def load_spans(panel: Path) -> dict[str, list[tuple[str, str]]]:
    spans: dict[str, list[tuple[str, str]]] = {}
    with panel.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans.setdefault(r["security_code"].zfill(6), []).append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31"))
    return spans


def read_pv(path: Path, spans) -> dict[tuple[str, str], float]:
    """面板在册期内的 (代码, 日期) → `P/V`。"""
    out: dict[tuple[str, str], float] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        hdr = next(rd)
        ic, idt, iv = (hdr.index(c) for c in ("security_code", "date", "valuation_ratio"))
        for row in rd:
            code, day = row[ic].zfill(6), row[idt]
            if not any(a <= day <= b for a, b in spans.get(code, ())):
                continue
            try:
                out[(code, day)] = float(row[iv])
            except (TypeError, ValueError, IndexError):
                pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="只报当前值，不对基准校验")
    ap.add_argument("--cand-states", type=Path, default=CAND_STATES,
                    help="候选侧逐日状态；缺省即生产文件。给别的文件时只报读数，供换估值口径的臂作诊断")
    ap.add_argument("--hold-states", type=Path, default=HOLD_STATES, help="持仓侧逐日状态；缺省即生产文件")
    args = ap.parse_args()

    spans = load_spans(PANEL)
    cand = read_pv(args.cand_states, spans)
    hold = read_pv(args.hold_states, spans)

    gaps = [cand[k] - hold[k] for k in cand.keys() & hold.keys()
            if SOURCE_PV_LO <= hold[k] <= SOURCE_PV_HI]
    if not gaps:
        print("两侧无重叠观测落在换仓源操作区间——先查面板与逐日文件是否对得上", file=sys.stderr)
        return 2
    gaps.sort()
    n = len(gaps)
    q = lambda p: gaps[int(p * (n - 1))]
    mean_gap = statistics.mean(gaps)
    nonzero = [x for x in gaps if x > 1e-9]
    share = len(nonzero) / n
    print(f"换仓源操作区间 持仓侧 P/V ∈ [{SOURCE_PV_LO}, {SOURCE_PV_HI}]：两侧共有观测 {n:,}")
    print(f"  g = 候选侧 P/V − 持仓侧 P/V：**均值 {mean_gap:.4f}**"
          f"｜有差观测 {len(nonzero):,}（{share:.1%}）｜P90 {q(0.90):.4f}｜P99 {q(0.99):.4f}")
    if nonzero:
        print(f"  只看有差者：中位 {statistics.median(nonzero):.4f}｜均值 {statistics.mean(nonzero):.4f}")

    if args.baseline:
        print(f"\n（基准模式）把 BASELINE_MEAN_GAP 设为 {mean_gap:.4f}、"
              f"BASELINE_NONZERO_SHARE 设为 {share:.3f}，并同步 §6.7 守卫步")
        return 0
    drift = mean_gap - BASELINE_MEAN_GAP
    print(f"  在册基准 均值 {BASELINE_MEAN_GAP:.4f}（有差占比 {BASELINE_NONZERO_SHARE:.1%}）"
          f"｜漂移 {drift:+.4f}｜容差 ±{TOLERANCE:.2f}")
    if abs(drift) > TOLERANCE:
        print(f"\n**标度漂移超限**：两套 V 的差距已变 {drift:+.4f}，"
              f"换仓边际的实际严格度由 ≈{BASELINE_MEAN_GAP + MARGIN:.4f} 变为 ≈{mean_gap + MARGIN:.4f}"
              f"——按 §12 重扫换仓边际后再重定本基准。")
        return 1
    print("\n未超限：已标定的换仓边际仍在原标度上，不必重扫。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
