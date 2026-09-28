#!/usr/bin/env python3
"""OI-223 研究：折现率按公司风险分档的时点基线表（设计见 docs/reports/oi223_design_draft_2026-09-28.zh.md，用户 2026-09-28 审定）。

每年 5 月 1 日（年报法定截止日之后）按当时已公告的年报，对有 ROIC 路径三大报表、非金融的公司打分：
  风险（权重 0.7，四项百分位的均值）：近十年 ROIC 变异系数、近十年年度 NOPAT 自前高的最大跌幅、
    近十年年报带中周期守卫生效（peak_weight 或 trough_weight > 0）的年份占比、最新年报账面杠杆
    max(0, 有息负债 − 超额现金) ÷ 投入资本；
  质量（权重 0.3，百分位）：近十年 ROIC 中位。
综合分 = 0.7 × 风险 − 0.3 × 质量（越高越险），当年横截面按 10/20/40/20/10 分入 T1～T5（r = 8%～12%）；
年报不足 5 年的不参与排名，取 T4（11%）。输出只供研究开关 `--discount-tiers` 读取，生产不用。

    python3 scripts/build_discount_rate_tiers.py --bands data/processed/roic_bands.csv \\
        --out data/processed/discount_rate_tiers_pit.csv
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import roic_inputs  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402

TIERS = (("T1", 0.08, 0.10), ("T2", 0.09, 0.20), ("T3", 0.10, 0.40), ("T4", 0.11, 0.20), ("T5", 0.12, 0.10))
SHORT_HISTORY = ("T4", 0.11)
MIN_YEARS = 5
RISK_WEIGHT, QUALITY_WEIGHT = 0.7, 0.3


def pct_ranks(values: dict[str, float]) -> dict[str, float]:
    """横截面百分位（0～1，同值取平均秩）。"""
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    out, i = {}, 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = (i + j) / 2 / max(len(ordered) - 1, 1)
        for k in range(i, j + 1):
            out[ordered[k][0]] = rank
        i = j + 1
    return out


def guard_share(bands: dict[str, list[tuple[str, str, bool]]], code: str, as_of: str) -> float | None:
    """近十个年报带（可得日 ≤ as_of）里周期守卫生效的占比。"""
    rows = [(rd, g) for rd, av, g in bands.get(code, ()) if av <= as_of]
    latest = {}
    for rd, g in rows:
        latest[rd] = g
    years = sorted(latest)[-10:]
    return sum(latest[y] for y in years) / len(years) if len(years) >= MIN_YEARS else None


def scores(years: list, guard: float | None) -> dict | None:
    ordered = sorted(years, key=lambda y: y.period)
    rois = [r for r in (roic_inputs.roic_of(y, p) for p, y in zip([None] + ordered[:-1], ordered)) if r is not None][-10:]
    nopat = [y.nopat for y in ordered if y.nopat is not None][-10:]
    if len(rois) < MIN_YEARS or len(nopat) < MIN_YEARS or guard is None:
        return None
    mean = statistics.mean(rois)
    cv = statistics.pstdev(rois) / abs(mean) if mean else float("inf")
    peak, dd = None, 0.0
    for v in nopat:
        peak = v if peak is None else max(peak, v)
        if peak and peak > 0:
            dd = max(dd, min(1.0, 1.0 - v / peak) if v > 0 else 1.0)
    last = ordered[-1]
    ic = last.invested_capital
    lev = max(0.0, (last.interest_debt or 0.0) - (last.excess_cash or 0.0)) / ic if ic and ic > 0 else None
    if lev is None:
        return None
    return dict(roic_cv=cv, nopat_drawdown=dd, guard_share=guard, leverage=lev, roic_median=statistics.median(rois))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bands", type=Path, default=ROOT / "data/processed/roic_bands.csv")
    ap.add_argument("--first-year", type=int, default=2007)
    ap.add_argument("--last-year", type=int, default=2026)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    names = {}
    with (ROOT / "data/raw/a_share_securities.csv").open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            names[r["security_code"].zfill(6)] = r["security_name"]
    bands: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
    with args.bands.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["report_date"].endswith("12-31") and r["status"] == "ok" and r.get("roic_path") in ("growth", "zero_growth"):
                g = any(float(r.get(k) or 0) > 0 for k in ("peak_weight", "trough_weight"))
                bands[r["security_code"]].append((r["report_date"], r["available_at"], g))
    codes = {c for c in names if not is_divspread_financial(c, names[c])}
    roic_years = roic_inputs.load_statements(codes, roic_inputs.STMT_DIR, ic_floor=0.1, caliber="nonop", notice_cap=True,
                                             restricted_cash="notes_wc")
    out_rows = []
    for year in range(args.first_year, args.last_year + 1):
        as_of = f"{year}-05-01"
        pool, short = {}, []
        for code, by_period in roic_years.items():
            hist = roic_inputs.years_before(by_period, as_of, 11)
            if not hist or hist[0].is_financial:
                continue
            s = scores(hist, guard_share(bands, code, as_of))
            if s is None:
                short.append(code)
            else:
                pool[code] = s
        risk_keys = ("roic_cv", "nopat_drawdown", "guard_share", "leverage")
        ranks = {k: pct_ranks({c: s[k] for c, s in pool.items()}) for k in (*risk_keys, "roic_median")}
        composite = {c: RISK_WEIGHT * statistics.mean(ranks[k][c] for k in risk_keys) - QUALITY_WEIGHT * ranks["roic_median"][c]
                     for c in pool}
        ordered = sorted(composite, key=lambda c: (composite[c], c))
        n, start = len(ordered), 0
        for i, (tier, r, share) in enumerate(TIERS):
            end = n if i == len(TIERS) - 1 else start + round(share * n)
            for c in ordered[start:end]:
                out_rows.append(dict(security_code=c, security_name=names.get(c, ""), effective_from=as_of,
                                     effective_to=f"{year + 1}-04-30", tier=tier, r=f"{r:.2f}", composite=f"{composite[c]:.4f}",
                                     **{k: f"{pool[c][k]:.4f}" for k in (*risk_keys, "roic_median")}, basis="baseline"))
            start = end
        for c in short:
            out_rows.append(dict(security_code=c, security_name=names.get(c, ""), effective_from=as_of, effective_to=f"{year + 1}-04-30",
                                 tier=SHORT_HISTORY[0], r=f"{SHORT_HISTORY[1]:.2f}", composite="", roic_cv="", nopat_drawdown="",
                                 guard_share="", leverage="", roic_median="", basis="short_history"))
        print(year, "ranked", n, "short", len(short), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(sorted(out_rows, key=lambda r: (r["security_code"], r["effective_from"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
