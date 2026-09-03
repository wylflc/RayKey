#!/usr/bin/env python3
"""A/B 配对差的归因集中度（L3 结果层：`docs/000_Ashare_workflow.md` §12.1 第 11 款）。

两条臂的滚动读数差 Δ 是决策依据，但 Δ 本身可能全部来自一两只股票的一两段持仓——
那种情况下这轮 A/B 测的是运气，不是机制。本脚本按代码把 Δ 拆开，回答：

    **这个 Δ 由多少只股票撑起来？**

口径：逐臂读 `*_trades.csv` 的闭合周期，按代码汇总 `contrib` 列（逐日「盈亏 ÷ 前一日净资产」的累计贡献，
与 §12.1 第 3 款「前五赢家」同一把尺），逐代码相减得 `Δ_code`，再报集中度。两个文件任一没有 `contrib` 列
（旧引擎产物）时退回名义盈亏 `proceeds − invested + dividends`。

集中度按两个分母各报一次，因为它们回答不同的问题：
* **净额占比** `前 N 个 Δ_code 之和 ÷ 总 Δ`——「结论靠谁撑」。可以 >100%（其余为负时）。
* **总动量占比** `前 N 个 |Δ_code| ÷ Σ|Δ_code|`——「改动搅动了多少只票」。恒在 0~1。

净额占比 >100% 意味着扣掉这几只后 Δ 反号，属最脆的一类；此时该 Δ 不应作采纳依据。

用法::

    python3 scripts/experimental/delta_attribution.py \
        --base /path/bt_base/BASE_trades.csv --arm /path/bt_arm/ARM_trades.csv
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def load_pnl(path: Path) -> dict[str, float]:
    """逐代码已实现盈亏 = Σ(proceeds − invested + dividends)。"""
    out: dict[str, float] = defaultdict(float)
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("exit_date"):
                continue                      # 未平仓周期不计（两臂同口径）
            out[r["security_code"]] += (float(r["proceeds"]) - float(r["invested"])
                                        + float(r.get("dividends") or 0.0))
    return dict(out)


def load_contrib(path: Path) -> tuple[dict[str, float], bool]:
    """逐代码累计贡献 = Σ `contrib`（逐日「盈亏 ÷ 前一日净资产」累计）；返回 (字典, 是否贡献口径)。
    文件没有 `contrib` 列时退回 `load_pnl` 的名义盈亏并返回 False。"""
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if "contrib" not in (reader.fieldnames or []):
            return load_pnl(path), False
        out: dict[str, float] = defaultdict(float)
        for r in reader:
            if not r.get("exit_date"):
                continue
            out[r["security_code"]] += float(r["contrib"] or 0.0)
    return dict(out), True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", type=Path, required=True, help="对照臂 *_trades.csv")
    ap.add_argument("--arm", type=Path, required=True, help="待测臂 *_trades.csv")
    ap.add_argument("--names", type=Path, default=None, help="可选：代码→名称 CSV")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    (base, b_rel), (arm, a_rel) = load_contrib(args.base), load_contrib(args.arm)
    rel = b_rel and a_rel
    if not rel:                                   # 两臂必须同一把尺
        base, arm = load_pnl(args.base), load_pnl(args.arm)
    fmt = (lambda v: f"{v:+.4f}") if rel else (lambda v: f"{v:,.0f}")
    unit = "贡献（盈亏÷当时净资产）" if rel else "已实现盈亏"
    codes = set(base) | set(arm)
    delta = {c: arm.get(c, 0.0) - base.get(c, 0.0) for c in codes}
    delta = {c: v for c, v in delta.items() if abs(v) > 1e-6}
    if not delta:
        print("两臂逐代码盈亏完全一致，Δ 为 0。")
        return 0

    total = sum(delta.values())
    gross = sum(abs(v) for v in delta.values())
    ranked = sorted(delta.items(), key=lambda kv: -abs(kv[1]))

    print(f"尺度：{unit}")
    print(f"对照臂 {args.base.name}：{len(base):,} 只、合计 {fmt(sum(base.values()))}")
    print(f"待测臂 {args.arm.name}：{len(arm):,} 只、合计 {fmt(sum(arm.values()))}")
    print(f"\n净 Δ = {fmt(total)}    有 Δ 的代码 {len(delta):,} 只    Σ|Δ_code| = {fmt(gross)}")

    print(f"\n{'#':>3} {'代码':<8}{'Δ_code':>16}{'净额累计占比':>14}{'动量累计占比':>14}")
    cum = cum_abs = 0.0
    for i, (code, v) in enumerate(ranked[:args.top], 1):
        cum += v
        cum_abs += abs(v)
        share = f"{cum / total:.1%}" if abs(total) > 1e-6 else "—"
        print(f"{i:>3} {code:<8}{fmt(v):>16}{share:>14}{cum_abs / gross:>14.1%}")

    print("\n集中度：")
    for n in (1, 3, 5):
        if len(ranked) < n:
            continue
        s = sum(v for _, v in ranked[:n])
        net = f"{s / total:.1%}" if abs(total) > 1e-6 else "—"
        gs = sum(abs(v) for _, v in ranked[:n]) / gross
        print(f"  前 {n} 只：净额占比 {net}   总动量占比 {gs:.1%}")

    s3 = sum(v for _, v in ranked[:3])
    if abs(total) > 1e-6 and (s3 / total) > 1.0:
        print("\n⚠ 前三只的净额占比 >100%——扣掉它们后 Δ 反号。该 Δ 不应作采纳依据"
              "（§12.1 第 11 款）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
