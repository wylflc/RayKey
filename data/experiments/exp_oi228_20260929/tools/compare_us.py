#!/usr/bin/env python3
"""OI-228 对美股历史状态的影响：v4.218 逐申报带（exp_oi226_20260928/us_r2/）与生产逐日状态 → 本轮 us/。
输出：标准输出（作业写 us/compare.txt）与 us/compare.json。
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
OLD_BANDS = ROOT / "data/experiments/exp_oi226_20260928/us_r2/us_valuation_bands.csv"
NEW_BANDS = EXP / "us" / "us_valuation_bands.csv"
OLD_STATES = ROOT / "data/processed/us_daily_states_adopted.csv"
NEW_STATES = Path(sys.argv[1]) if len(sys.argv) > 1 else EXP / "us" / "states_adopted.csv"
MEMBERS = ROOT / "data/processed/us_sp500_members.csv"


def load(path: Path, key) -> dict:
    with path.open(encoding="utf-8") as fh:
        return {key(r): r for r in csv.DictReader(fh)}


def spans() -> dict:
    """{CIK: [(入选日, 剔除日)]}：标普 500 成员区间（`to` 空为至今）。"""
    out = defaultdict(list)
    with MEMBERS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["cik"]].append((r["from"], r["to"] or "9999-12-31"))
    return out


def main() -> int:
    ticker = {}
    with MEMBERS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ticker.setdefault(r["cik"], r["ticker"])
    a = load(OLD_BANDS, lambda r: (r["cik"], r["filed"]))
    b = load(NEW_BANDS, lambda r: (r["cik"], r["filed"]))
    changed = [dict(cik=k[0], ticker=ticker.get(k[0], ""), filed=k[1], old_status=a.get(k, {}).get("status", "—"),
                    new_status=b[k]["status"], old=a.get(k, {}).get("value", ""), new=b[k]["value"], period=b[k]["period"],
                    reason=b[k]["reason"])
               for k in sorted(b) if k not in a or a[k]["value"] != b[k]["value"] or a[k]["status"] != b[k]["status"]]
    gone = [k for k in a if k not in b]
    by_cik = defaultdict(list)
    for c in changed:
        by_cik[c["cik"]].append(c)
    print(f"逐申报带：{len(b)} 个申报点（v4.218 {len(a)}，消失 {len(gone)}），V 或状态变化 {len(changed)} 个／{len(by_cik)} 家")
    summary = {}
    for cik, cs in sorted(by_cik.items(), key=lambda kv: -len(kv[1])):
        ratios = [float(c["new"]) / float(c["old"]) for c in cs if c["old"] and c["new"]]
        trans = defaultdict(int)
        for c in cs:
            trans[f"{c['old_status']}→{c['new_status']}"] += 1
        summary[cik] = dict(ticker=cs[0]["ticker"], n=len(cs), first=cs[0]["filed"], last=cs[-1]["filed"],
                            v_ratio_median=statistics.median(ratios) if ratios else None,
                            v_ratio_min=min(ratios) if ratios else None, v_ratio_max=max(ratios) if ratios else None,
                            transitions=dict(trans), reasons=sorted({c["reason"] for c in cs if c["new_status"] != "ok"})[:3])
        s = summary[cik]
        med = f"新/旧 V 中位 {s['v_ratio_median']:.3f}（{s['v_ratio_min']:.3f}～{s['v_ratio_max']:.3f}）" if ratios else ""
        print(f"  {s['ticker']} {cik}: {s['n']} 个申报点 {s['first']}～{s['last']} {med} {s['transitions']} {s['reasons']}")
    # 逐日状态：逐公司 P/V 变化的交易日数与末日 P/V
    def states(path):
        out = defaultdict(dict)
        with path.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[r["security_code"]][r["date"]] = r["valuation_ratio"]
        return out
    old, new = states(OLD_STATES), states(NEW_STATES)
    rows_old, rows_new = sum(len(v) for v in old.values()), sum(len(v) for v in new.values())
    print(f"逐日状态：{rows_old:,} 行／{len(old)} 家 → {rows_new:,} 行／{len(new)} 家")
    st = {}
    member = spans()
    for cik in sorted(set(old) | set(new)):
        o, n = old.get(cik, {}), new.get(cik, {})
        days = set(o) | set(n)
        diff = [d for d in days if o.get(d) != n.get(d)]
        if diff:
            last = max(days)
            in_member = sum(1 for d in diff if any(a <= d <= b for a, b in member.get(cik, ())))
            st[cik] = dict(ticker=ticker.get(cik, ""), days=len(diff), member_days=in_member, only_old=sum(1 for d in diff if d not in n),
                           only_new=sum(1 for d in diff if d not in o), first=min(diff), last=max(diff),
                           end_pv_old=o.get(last, ""), end_pv_new=n.get(last, ""))
            print(f"  {st[cik]['ticker']} {cik}: {len(diff)} 个交易日变化（成员期内 {in_member}；只在旧 {st[cik]['only_old']}、只在新 {st[cik]['only_new']}）"
                  f" {min(diff)}～{max(diff)}；末日 {last} P/V {o.get(last, '—')} → {n.get(last, '—')}")
    (EXP / "us" / "compare.json").write_text(json.dumps(dict(bands=summary, states=st, rows_old=rows_old, rows_new=rows_new,
                                                             bands_changed=len(changed), bands_gone=len(gone)),
                                                        ensure_ascii=False, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
