#!/usr/bin/env python3
"""OI-226：OI-150 前向检验按现行口径重跑（本目录 oi150/）与 09-07 结案记录（exp_oi150_overseas_forward/）的对比读数。"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
OLD = ROOT / "data/experiments/exp_oi150_overseas_forward"
NEW = EXP / "oi150"


def rows(path: Path) -> dict[tuple[str, str], dict]:
    with path.open(encoding="utf-8") as fh:
        return {(r["cik"], r["date"]): r for r in csv.DictReader(fh)}


def main() -> int:
    a, b = json.loads((OLD / "result.json").read_text()), json.loads((NEW / "result.json").read_text())
    out = {"outcome": (a["outcome"], b["outcome"]), "reasons": (a["reasons"], b["reasons"]),
           "status": (a["status"], b["status"])}
    print(f"结论 {a['outcome']} → {b['outcome']}；公司月 {a['company_months']} → {b['company_months']}")
    print(f"状态 {a['status']}\n  → {b['status']}")
    for h in ("3", "5"):
        ha, hb = a["horizons"][h], b["horizons"][h]
        out[h] = {k: (ha[k], hb[k]) for k in ("n", "rho", "negative_groups", "gap_pp", "descriptive_criteria_pass")}
        print(f"{h}年：有收益公司月 {ha['n']} → {hb['n']}；合并 Spearman {ha['rho']:+.5f} → {hb['rho']:+.5f}；"
              f"负相关年组 {ha['negative_groups']} → {hb['negative_groups']}/11；便宜档−比较档 "
              f"{ha['gap_pp']:+.2f} → {hb['gap_pp']:+.2f} pp/年；两项判据 {ha['descriptive_criteria_pass']} → {hb['descriptive_criteria_pass']}")
    old_path = OLD / "pv_monthly.csv"
    if old_path.exists():
        pa, pb = rows(old_path), rows(NEW / "pv_monthly.csv")
        both = [k for k in pb if pa.get(k, {}).get("value") and pb[k]["value"]]
        ratios = [float(pb[k]["value"]) / float(pa[k]["value"]) for k in both]
        moved = Counter(f"{pa[k]['status']}→{pb[k]['status']}" for k in pb if k in pa and pa[k]["status"] != pb[k]["status"])
        out["values"] = dict(both_valued=len(both), changed=sum(abs(r - 1) > 1e-6 for r in ratios),
                             ratio_median=statistics.median(ratios) if ratios else None, status_moves=dict(moved))
        print(f"两次都有 V 的公司月 {len(both)}，V 变化 {out['values']['changed']}，新/旧 V 中位 {out['values']['ratio_median']}；"
              f"状态迁移 {dict(moved.most_common(8))}")
    (NEW / "compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
