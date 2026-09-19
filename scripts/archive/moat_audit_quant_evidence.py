#!/usr/bin/env python3
"""关注池护城河审核的量化证据表（2026-09-07 用户点名全池复核）。

对 `worth_attention` 每家公司，从 `data/raw/financials/` 逐季面板取 FY 年报行（12-31）与最新中报，
算十年维度的回报持续性：加权 ROE 中位／最低／≥15% 年数、毛利率首末五年均值、归母净利与营收 CAGR、
经营现金流÷净利（每股口径），并按 `a_share_securities.csv` 的 `industry` 算同业逐年 ROE 分位的中位
（同业 = 同行业全部 A 股当年有 ROE 的公司）。**脚本只连接数据，不作任何判定**（§5.2）。
"""
from __future__ import annotations
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIN = ROOT / "data/raw/financials"
YEARS = list(range(2015, 2026))
OUT = ROOT / "data/interim/moat_audit_2026-09-07/quant_evidence.csv"


def f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def load_period(day: str) -> dict[str, dict]:
    p = FIN / f"{day}.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as h:
        return {r["security_code"]: r for r in csv.DictReader(h)}


def cagr(a, b, n):
    if a is None or b is None or a <= 0 or b <= 0 or n <= 0:
        return None
    return (b / a) ** (1 / n) - 1


def main() -> int:
    tiers = list(csv.DictReader((ROOT / "data/processed/a_share_watchlist_quality_tiers.csv").open(encoding="utf-8")))
    pool = [r for r in tiers if r["attention_class"] == "worth_attention"]
    with (ROOT / "data/raw/a_share_securities.csv").open(encoding="utf-8-sig") as h:
        # 行业标签有「C 制造业」与「制造业」两种写法，去掉门类字母前缀后合并；分位按证监会门类算，只作粗尺
        industry = {r["security_code"]: re.sub(r"^[A-Z]\s*", "", r.get("industry", "")) for r in csv.DictReader(h)}
    annual = {y: load_period(f"{y}-12-31") for y in YEARS}
    h1 = load_period("2026-06-30")
    print("FY coverage:", {y: len(v) for y, v in annual.items()}, "| 2026H1:", len(h1), file=sys.stderr)
    # 同业分位：每年按行业收集 ROE
    ind_roe: dict[tuple[int, str], list[float]] = defaultdict(list)
    for y, rows in annual.items():
        for code, r in rows.items():
            v = f(r.get("weightavg_roe"))
            if v is not None and industry.get(code):
                ind_roe[(y, industry[code])].append(v)
    cols = ["security_code", "security_name", "quality_tier", "industry", "industry_n", "fy_years",
            "roe_median", "roe_min", "roe_years_ge15", "roe_latest_fy", "roe_2026h1",
            "roe_pctl_median", "roe_pctl_min", "roe_pctl_years_ge80",
            "gm_first5_avg", "gm_last5_avg", "gm_latest_fy",
            "rev_cagr", "ni_cagr", "ni_negative_years", "ocf_to_ni_median", "roe_series", "pctl_series"]
    out = []
    for r in pool:
        code = r["security_code"]
        ind = industry.get(code, "")
        roe, pct, gm, ocf_ni, years = [], [], [], [], []
        rev, ni = {}, {}
        for y in YEARS:
            row = annual[y].get(code)
            if not row:
                continue
            v = f(row.get("weightavg_roe"))
            if v is None:
                continue
            years.append(y)
            roe.append(v)
            peers = ind_roe.get((y, ind), [])
            if len(peers) >= 5:
                pct.append(100.0 * sum(1 for p in peers if p < v) / len(peers))
            g = f(row.get("gross_margin"))
            gm.append((y, g))
            rev[y], ni[y] = f(row.get("total_operate_income")), f(row.get("parent_netprofit"))
            ocf, eps = f(row.get("op_cashflow_ps")), f(row.get("basic_eps"))
            if ocf is not None and eps and eps > 0:
                ocf_ni.append(ocf / eps)
        gm_first = [g for y, g in gm if y <= 2019 and g is not None]
        gm_last = [g for y, g in gm if y >= 2021 and g is not None]
        fy_last = years[-1] if years else None
        y0 = years[0] if years else None
        h = h1.get(code, {})
        n_ind = len(ind_roe.get((fy_last, ind), [])) if fy_last else 0
        out.append({
            "security_code": code, "security_name": r["security_name"], "quality_tier": r["quality_tier"],
            "industry": ind, "industry_n": n_ind, "fy_years": len(years),
            "roe_median": round(statistics.median(roe), 2) if roe else "",
            "roe_min": round(min(roe), 2) if roe else "",
            "roe_years_ge15": sum(1 for v in roe if v >= 15),
            "roe_latest_fy": roe[-1] if roe else "",
            "roe_2026h1": f(h.get("weightavg_roe")) if h else "",
            "roe_pctl_median": round(statistics.median(pct), 0) if pct else "",
            "roe_pctl_min": round(min(pct), 0) if pct else "",
            "roe_pctl_years_ge80": sum(1 for p in pct if p >= 80),
            "gm_first5_avg": round(statistics.mean(gm_first), 1) if gm_first else "",
            "gm_last5_avg": round(statistics.mean(gm_last), 1) if gm_last else "",
            "gm_latest_fy": ([g for _y, g in gm if g is not None] or [""])[-1],
            "rev_cagr": (round(100 * c, 1) if (c := cagr(rev.get(y0), rev.get(fy_last), (fy_last or 0) - (y0 or 0))) is not None else ""),
            "ni_cagr": (round(100 * c, 1) if (c := cagr(ni.get(y0), ni.get(fy_last), (fy_last or 0) - (y0 or 0))) is not None else ""),
            "ni_negative_years": sum(1 for v in ni.values() if v is not None and v < 0),
            "ocf_to_ni_median": round(statistics.median(ocf_ni), 2) if ocf_ni else "",
            "roe_series": " ".join(f"{y}:{v:.1f}" for y, v in zip(years, roe)),
            "pctl_series": " ".join(f"{p:.0f}" for p in pct),
        })
    with OUT.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=cols)
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} 家 → {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
