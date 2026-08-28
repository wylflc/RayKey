#!/usr/bin/env python3
"""持仓侧池模型带（§6.7 第 4 步）：逐票取候选侧生产带与 B2 池带中 `intrinsic_value` 较高的一行。

扫描器 `--hold-bands` 与持仓跟踪读它：§9.3.1 减持线与换仓来源按持仓侧 P/V 判，买入线与候选排序仍读
`a_share_pool_model_bands_adopted.csv`。两份输入都须已各自跑完第 4 步的预告叠加与除权归一化。

规则：两侧都 `ok` 且有 V → V 大者，相等取候选侧；只有一侧 `ok` → 取该侧；两侧都非 `ok` → 写候选侧行
（无 V、`model_evaluated_at` 随行传下，§6.5.2.4 无法估值）。输出列 = 候选侧列 + `hold_source`（base／b2）。

用法：
    python3 scripts/build_hold_model_bands.py            # 缺省路径
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "data/processed/a_share_pool_model_bands_adopted.csv"
DEFAULT_B2 = ROOT / "data/processed/a_share_pool_model_bands_b2.csv"
DEFAULT_OUT = ROOT / "data/processed/a_share_pool_model_bands_hold.csv"


def _iv(row: dict) -> float | None:
    if (row.get("status") or "ok") not in ("", "ok"):
        return None
    try:
        v = float(row.get("intrinsic_value") or "")
    except ValueError:
        return None
    return v if v > 0 else None


def load(path: Path) -> tuple[list[str], dict[str, dict]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows = {(r.get("security_code") or "").zfill(6): r for r in reader}
        return list(reader.fieldnames or []), rows


def main() -> int:
    ap = argparse.ArgumentParser(description="持仓侧池模型带 = 逐票取两口径较高 V")
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE)
    ap.add_argument("--b2", type=Path, default=DEFAULT_B2)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args()
    fields, base = load(a.base)
    _b2_fields, b2 = load(a.b2)
    only_b2 = sorted(set(b2) - set(base))
    if only_b2:
        print(f"  ⚠ B2 池带多出 {len(only_b2)} 只不在候选侧生产带（两侧成员应同为池成员）：{'、'.join(only_b2[:8])}")
    out_fields = fields + (["hold_source"] if "hold_source" not in fields else [])
    n_b2 = n_base = n_b2_only_ok = n_none = 0
    lifted: list[tuple[str, float, float]] = []
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with a.out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=out_fields, restval="")
        w.writeheader()
        for code in sorted(set(base) | set(b2)):
            rb, r2 = base.get(code), b2.get(code)
            vb, v2 = (_iv(rb) if rb else None), (_iv(r2) if r2 else None)
            if v2 is not None and (vb is None or v2 > vb):
                row, src = dict(r2), "b2"
                if vb is None:
                    n_b2_only_ok += 1
                else:
                    n_b2 += 1
                    lifted.append((str(rb.get("security_name") or code), vb, v2))
            elif vb is not None:
                row, src = dict(rb), "base"; n_base += 1
            else:
                row, src = dict(rb if rb is not None else r2), "base" if rb is not None else "b2"; n_none += 1
            row["hold_source"] = src
            w.writerow({k: row.get(k, "") for k in out_fields})
    print(f"持仓侧池带 {len(set(base) | set(b2))} 只 → {a.out.name}：B2 更高 {n_b2}｜候选侧更高或相等 {n_base}"
          f"｜仅 B2 可估 {n_b2_only_ok}｜两侧无法估值 {n_none}")
    for name, vb, v2 in sorted(lifted, key=lambda t: -(t[2] / t[1])):
        print(f"  · {name}：V {vb:.2f} → {v2:.2f}（+{v2 / vb - 1:.1%}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
