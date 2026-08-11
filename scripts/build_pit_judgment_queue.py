#!/usr/bin/env python3
"""在**全口径宇宙**（现存 + 退市）上构造逐股判定队列（OI-040 配套）。

与旧 `pit_panel.py build_queue` 的三处不同
------------------------------------------
1. **宇宙含退市公司**。旧版的 `listed` 取自本地行情目录，而该目录当时零覆盖退市股，
   等于把幸存者偏差直接烧进队列。现行情已补 `data/raw/a_share_delisted_roster.csv` 的 344 只。
2. **年份窗口可回溯到 2002**（旧版硬编码 `Y0, Y1 = 2009, 2025`）。回测长跑从 2002 起，
   队列只覆盖 2009+ 会让 2002-2008 段无时点名单可用。
3. **ROE 改用 `EPS/BPS` 推算，不再直接信 `weightavg_roe`**。实测该字段两边都有坏值：
   东财 600217·2013 给出「亏 1.17 亿却加权 ROE +35.49」，新浪 600448·2009 给出 −0.27
   而其自身净资产收益率为 −31.97。推算值在三个判例上与新浪净资产收益率精确吻合。
   仍读原字段做**一致性校验**，矛盾即打标 `roe_conflict`，交由判定环节处理，**不静默丢弃**。

本脚本**只决定「何时值得判」**（召回网），不做任何 worth_attention 判定——
判定口径见 `docs/Ashare_pit_judgment_protocol.md`。

用法::

    python3 scripts/build_pit_judgment_queue.py
    python3 scripts/build_pit_judgment_queue.py --since-year 2002 --until-year 2025
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIN = ROOT / "data/raw/financials"
OHLCV = ROOT / "data/raw/ohlcv"
ROSTER = ROOT / "data/raw/a_share_delisted_roster.csv"
CONTAM = ROOT / "data/processed/pit_attention/restatement_contamination.csv"
OUT = ROOT / "data/processed/pit_attention/judgment_queue.csv"

A_SHARE = re.compile(r"^(000|001|002|003|300|301|600|601|603|605|688|689)\d{3}$")


def _num(text):
    try:
        return float((text or "").strip())
    except (TypeError, ValueError):
        return None


def load_annuals() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for path in sorted(FIN.glob("*-12-31.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = row["security_code"]
                if (row.get("notice_date") or "").strip() and A_SHARE.match(code):
                    out[code][row["report_date"][:4]] = row
    return out


def first_traded() -> dict[str, str]:
    out = {}
    for path in sorted(OHLCV.glob("*.csv")):
        if path.stem.startswith("INDEX_"):
            continue
        with path.open(encoding="utf-8") as handle:
            handle.readline()
            line = handle.readline()
            if line:
                out[path.stem] = line.split(",", 1)[0]
    return out


def roe_of(row) -> tuple[float | None, bool]:
    """返回 (ROE 小数, 是否与原字段矛盾)。**推算优先**，见模块文档第 3 条。"""
    eps, bps = _num(row.get("basic_eps")), _num(row.get("bps"))
    stated = _num(row.get("weightavg_roe"))
    derived = eps / bps if (eps is not None and bps not in (None, 0)) else None
    if derived is None:
        return (stated / 100.0 if stated is not None else None), False
    conflict = stated is not None and abs(stated) > 1 and (stated > 0) != (derived > 0)
    return derived, conflict


def window(series: dict[str, dict], year: int, w: int = 5):
    vals, conflicts = [], 0
    for y in (str(x) for x in range(year - w + 1, year + 1)):
        row = series.get(y)
        if row is None:
            continue
        roe, conflict = roe_of(row)
        profit = _num(row.get("parent_netprofit"))
        if roe is None or profit is None:
            continue
        conflicts += conflict
        vals.append((roe, profit, (_num(row.get("total_operate_income")) or 0) / 1e8,
                     (_num(row.get("gross_margin")) or 0) / 100.0))
    if len(vals) < 3:
        return None
    return {"roe": statistics.fmean(v[0] for v in vals), "roemin": min(v[0] for v in vals),
            "profit": vals[-1][1], "revenue": vals[-1][2], "gross": vals[-1][3],
            "conflicts": conflicts}


def signature(p) -> bool:
    """四条并联的护城河财务签名（§12.9.13 校准）。**只决定何时值得判，不是判定本身。**"""
    if p is None or p["profit"] <= 0:
        return False
    return ((p["roe"] >= 0.15 and p["roemin"] >= 0.08 and p["revenue"] >= 10)
            or (p["gross"] >= 0.40 and p["revenue"] >= 5)
            or p["revenue"] >= 100
            or (p["roe"] >= 0.10 and p["revenue"] >= 30))


def main() -> int:
    parser = argparse.ArgumentParser(description="全口径宇宙的逐股判定队列")
    parser.add_argument("--since-year", type=int, default=2002)
    parser.add_argument("--until-year", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    annuals = load_annuals()
    listed = first_traded()
    delisted = {}
    if ROSTER.exists():
        for row in csv.DictReader(ROSTER.open(newline="", encoding="utf-8")):
            if row["status"] == "delisted":
                delisted[row["security_code"]] = row["last_trade_date"]
    contaminated: dict[str, set[str]] = defaultdict(set)
    if CONTAM.exists():
        for row in csv.DictReader(CONTAM.open(newline="", encoding="utf-8")):
            contaminated[row["security_code"]].add(row["year"])

    rows, no_price = [], 0
    for code, series in annuals.items():
        start = listed.get(code)
        if start is None:
            no_price += 1
            continue
        years, conflicts = [], 0
        for year in range(args.since_year, args.until_year + 1):
            if start > f"{year}-12-31":
                continue
            snap = window(series, year)
            if snap and signature(snap):
                years.append(year)
                conflicts += snap["conflicts"]
        if not years:
            continue
        peak = max(window(series, y)["revenue"] for y in years)
        rows.append({
            "security_code": code, "first_sig_year": years[0], "last_sig_year": years[-1],
            "n_sig_years": len(years), "peak_revenue_yi": f"{peak:.1f}",
            "first_traded": start,
            "is_delisted": "Y" if code in delisted else "N",
            "last_trade_date": delisted.get(code, ""),
            "roe_conflict_periods": conflicts,
            "contaminated_years": ";".join(sorted(contaminated.get(code, ()))),
        })
    rows.sort(key=lambda r: (r["first_sig_year"], -float(r["peak_revenue_yi"])))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    n_del = sum(1 for r in rows if r["is_delisted"] == "Y")
    n_con = sum(1 for r in rows if r["contaminated_years"])
    print(f"判定队列 {len(rows):,} 家 → {args.out}")
    print(f"  其中退市股 {n_del}｜含重述污染年的 {n_con}｜有 ROE 矛盾期的 "
          f"{sum(1 for r in rows if r['roe_conflict_periods'])}")
    print(f"  首次签名年分布（前 8）："
          f"{sorted({r['first_sig_year'] for r in rows})[:8]}")
    if no_price:
        print(f"  ⚠ {no_price:,} 家有财报但**无行情文件**，已排除——"
              f"行情补齐后须重跑，否则又是一次静默丢弃")
    return 0


if __name__ == "__main__":
    sys.exit(main())
