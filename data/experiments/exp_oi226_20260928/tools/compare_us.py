#!/usr/bin/env python3
"""OI-226 美股历史状态重建的归因读数：逐申报带（OI-210 记录 → 复现 → WACC=r 引擎 → OI-216 标签组）与逐日状态前后对比。

输入：exp_oi210_20260924/us/us_valuation_bands.csv（09-24 记录）、本目录 us/us_valuation_bands{_oi210,_pre4214,}.csv、
us/old_states_adopted.csv（重建前逐日状态副本）、data/processed/us_daily_states_adopted.csv（重建后）。
输出：标准输出（作业写 us/compare.txt）与 us/compare.json。
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
US = EXP / "us"
REF = ROOT / "data/experiments/exp_oi210_20260924/us/us_valuation_bands.csv"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"
NEW_STATES = ROOT / "data/processed/us_daily_states_adopted.csv"
OLD_STATES = US / "old_states_adopted.csv"


def bands(path: Path) -> dict[tuple[str, str], dict]:
    with path.open(encoding="utf-8") as fh:
        return {(r["cik"], r["filed"]): r for r in csv.DictReader(fh)}


def num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def transition(a: dict, b: dict) -> dict:
    keys = sorted(set(a) | set(b))
    missing = [k for k in keys if k not in a or k not in b]
    changed, status = [], Counter()
    for k in keys:
        if k not in a or k not in b:
            continue
        ra, rb = a[k], b[k]
        if ra["status"] != rb["status"]:
            status[f"{ra['status']}→{rb['status']}"] += 1
        va, vb = num(ra["value"]), num(rb["value"])
        if (va is None) != (vb is None) or (va is not None and abs(vb / va - 1) > 1e-6):
            changed.append((k, va, vb))
    ratios = [vb / va for _k, va, vb in changed if va and vb]
    return dict(filings=len(keys), key_mismatch=len(missing), value_changed=len(changed),
                ciks_changed=len({k[0] for k, _a, _b in changed}), status_changes=dict(status),
                ratio_median=statistics.median(ratios) if ratios else None,
                ratio_p10=statistics.quantiles(ratios, n=10)[0] if len(ratios) >= 10 else None,
                ratio_p90=statistics.quantiles(ratios, n=10)[-1] if len(ratios) >= 10 else None,
                rows=changed)


def states_summary(path: Path) -> dict:
    by_year: dict[str, list[float]] = defaultdict(list)
    ciks: set[str] = set()
    n, last = 0, ""
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n += 1
            ciks.add(r["security_code"])
            last = max(last, r["date"])
            by_year[r["date"][:4]].append(float(r["valuation_ratio"]))
    return dict(rows=n, ciks=len(ciks), last_date=last,
                pv_median_by_year={y: round(statistics.median(v), 4) for y, v in sorted(by_year.items())},
                rows_by_year={y: len(v) for y, v in sorted(by_year.items())})


def main() -> int:
    ticker = {}
    with MEMBERS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ticker.setdefault(r["cik"], r["ticker"])
    ref, repro, pre, cur = bands(REF), bands(US / "us_valuation_bands_oi210.csv"), \
        bands(US / "us_valuation_bands_pre4214.csv"), bands(US / "us_valuation_bands.csv")
    steps = {"09-24 记录 → 复现（ee4a0325 代码）": transition(ref, repro),
             "复现 → 现行引擎 WACC=r（OI-216 前取数）": transition(repro, pre),
             "WACC=r → OI-216 标签组（现行代码）": transition(pre, cur),
             "09-24 记录 → 现行代码（合计）": transition(ref, cur)}
    out = {}
    for name, t in steps.items():
        rows = t.pop("rows")
        print(f"## {name}")
        print(f"申报点 {t['filings']}（键不一致 {t['key_mismatch']}），V 变化 {t['value_changed']} 个／{t['ciks_changed']} 家；"
              f"状态迁移 {t['status_changes'] or '无'}；新/旧 V 中位 {t['ratio_median']}（P10 {t['ratio_p10']}，P90 {t['ratio_p90']}）")
        if name.startswith("WACC=r → OI-216"):
            for (cik, filed), va, vb in rows:
                print(f"  {ticker.get(cik, cik)} {cik} {filed}: {va} → {vb}" + (f"（{(vb / va - 1) * 100:+.1f}%）" if va and vb else ""))
            t["rows"] = [dict(cik=c, ticker=ticker.get(c, ""), filed=f, old=va, new=vb) for (c, f), va, vb in rows]
        out[name] = t
    if OLD_STATES.exists() and NEW_STATES.exists():
        old, new = states_summary(OLD_STATES), states_summary(NEW_STATES)
        out["states"] = dict(before=old, after=new)
        print("## 逐日状态")
        print(f"重建前 {old['rows']} 行／{old['ciks']} 家（末日 {old['last_date']}）；重建后 {new['rows']} 行／{new['ciks']} 家（末日 {new['last_date']}）")
        for y in sorted(set(old["pv_median_by_year"]) | set(new["pv_median_by_year"])):
            print(f"  {y}: 行 {old['rows_by_year'].get(y, 0)} → {new['rows_by_year'].get(y, 0)}；P/V 中位 "
                  f"{old['pv_median_by_year'].get(y)} → {new['pv_median_by_year'].get(y)}")
    (US / "compare.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
