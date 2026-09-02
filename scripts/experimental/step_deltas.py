#!/usr/bin/env python3
"""相邻臂之间的逐起点配对差（拆解阶梯用；§12.172）。

`sweep_backtest_configs.py` 的 Δ 一律对标签为 `BASE` 的那条臂算，拆解阶梯要的却是
**每一步只动一件事**的步间 Δ——`A → B` 的差不能由 `Δ(A,BASE)` 与 `Δ(B,BASE)` 相减得到
（两个中位数之差不是配对差的中位）。本脚本直接从 sweep 的原始逐起点行重算。

用法::

    python3 scripts/experimental/step_deltas.py <sweep_out.txt> --path BASE GE_TROUGHOFF GE_BINARY GUARDEFF
    # 可给多条 --path；带 --ex5 时读去赢家那一遍（`EX5:` 前缀行）
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sweep_backtest_configs import FIELDS, EX5_PREFIX  # noqa: E402

KEYS = (("Δ主", "滚动5年年化中位"), ("Δ复利", "年化"),
        ("ΔP25", "滚动5年年化P25"), ("Δ回撤", "滚动5年回撤中位"))


def load(path: Path, ex5: bool) -> dict[str, dict[str, dict[str, float]]]:
    out: dict[str, dict[str, dict[str, float]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        p = line.split("|")
        if len(p) != 2 + len(FIELDS):
            continue
        label = p[0]
        is_ex = label.startswith(EX5_PREFIX)
        if is_ex != ex5:
            continue
        label = label[len(EX5_PREFIX):] if is_ex else label
        out.setdefault(label, {})[p[1]] = dict(zip(FIELDS, map(float, p[2:])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sweep", type=Path)
    ap.add_argument("--path", nargs="+", action="append", required=True,
                    help="一条阶梯的臂序，相邻两臂算一步；可重复给")
    ap.add_argument("--ex5", action="store_true", help="读去赢家那一遍")
    a = ap.parse_args()

    data = load(a.sweep, a.ex5)
    print(f"{a.sweep}（{'去赢家' if a.ex5 else '全样本'}）：{len(data)} 臂")
    for path in a.path:
        print("\n阶梯 " + " → ".join(path))
        for lo, hi in zip(path, path[1:]):
            if lo not in data or hi not in data:
                print(f"  {lo} → {hi}: 缺臂"); continue
            common = sorted(set(data[lo]) & set(data[hi]))
            cells = []
            for name, key in KEYS:
                d = [data[hi][s][key] - data[lo][s][key] for s in common]
                pos = sum(1 for v in d if v > 0)
                cells.append(f"{name} {statistics.median(d)*100:+.2f}（{pos}/{len(common)}）")
            print(f"  {lo} → {hi}: " + "  ".join(cells))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
