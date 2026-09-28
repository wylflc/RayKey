#!/usr/bin/env python3
"""OI-226 第二轮（台积电三项余项按 A 股口径：ifrs-full IFRS 16 租赁负债、其他流动金融资产不计现金类）对美股历史状态的影响：
第一轮（v4.217）逐申报带 us/us_valuation_bands.csv 与逐日状态副本 us_r2/old_states_adopted.csv → 本轮 us_r2/ 与
data/processed/us_daily_states_adopted.csv。输出：标准输出（作业写 us_r2/compare.txt）与 us_r2/compare.json。
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
OLD_BANDS, NEW_BANDS = EXP / "us" / "us_valuation_bands.csv", EXP / "us_r2" / "us_valuation_bands.csv"
OLD_STATES, NEW_STATES = EXP / "us_r2" / "old_states_adopted.csv", ROOT / "data/processed/us_daily_states_adopted.csv"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"


def load(path: Path, key) -> dict:
    with path.open(encoding="utf-8") as fh:
        return {key(r): r for r in csv.DictReader(fh)}


def main() -> int:
    ticker = {}
    with MEMBERS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ticker.setdefault(r["cik"], r["ticker"])
    a = load(OLD_BANDS, lambda r: (r["cik"], r["filed"]))
    b = load(NEW_BANDS, lambda r: (r["cik"], r["filed"]))
    changed = [dict(cik=k[0], ticker=ticker.get(k[0], ""), filed=k[1], old_status=a[k]["status"], new_status=b[k]["status"],
                    old=a[k]["value"], new=b[k]["value"], period=b[k]["period"])
               for k in sorted(b) if k not in a or a[k]["value"] != b[k]["value"] or a[k]["status"] != b[k]["status"]]
    print(f"逐申报带：{len(b)} 个申报点（第一轮 {len(a)}），V 或状态变化 {len(changed)} 个／{len({c['cik'] for c in changed})} 家")
    for c in changed:
        va, vb = (float(c["old"]) if c["old"] else None), (float(c["new"]) if c["new"] else None)
        pct = f"（{(vb / va - 1) * 100:+.2f}%）" if va and vb else ""
        print(f"  {c['ticker']} {c['cik']} {c['filed']} 报告期 {c['period']}: {c['old_status']} {c['old']} → {c['new_status']} {c['new']}{pct}")
    states = {}
    if OLD_STATES.exists():
        key = lambda r: (r["security_code"], r["date"])  # noqa: E731
        old, new = load(OLD_STATES, key), load(NEW_STATES, key)
        diff = defaultdict(list)
        for k in set(old) | set(new):
            vo = old.get(k, {}).get("intrinsic_value")
            vn = new.get(k, {}).get("intrinsic_value")
            if vo != vn:
                diff[k[0]].append((k[1], vo, vn, old.get(k, {}).get("valuation_ratio"), new.get(k, {}).get("valuation_ratio")))
        states = dict(rows_before=len(old), rows_after=len(new),
                      changed={ticker.get(c, c): dict(days=len(v), first=min(v)[0], last=max(v)[0],
                                                       last_values=max(v)[1:]) for c, v in diff.items()})
        print(f"逐日状态：{len(old)} → {len(new)} 行；V 变化的公司 {len(diff)} 家")
        for c, v in sorted(diff.items()):
            last = max(v)
            print(f"  {ticker.get(c, c)} {c}: {len(v)} 个交易日（{min(v)[0]}～{last[0]}），末日 V {last[1]} → {last[2]}，P/V {last[3]} → {last[4]}")
    (EXP / "us_r2" / "compare.json").write_text(json.dumps(dict(bands_changed=changed, states=states), ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
