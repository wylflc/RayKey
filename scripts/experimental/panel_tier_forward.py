#!/usr/bin/env python3
"""分档条件下的 `P/V` → 前向总回报校准（OI-070 护城河补偿实验的「一般」侧，2026-08-20）。

问题：同一个 `P/V`，强护城河公司（L1）其后的回报是否系统性高于 L2/L3？若是，统一终值假设
确实在结构性低估强护城河公司、补偿有数据支持；若否，「按护城河分档补偿」在全池上没有依据。

口径：
* 样本 = 面板在册期内每个 (代码, 月末) 的 `P/V`（取自逐日状态文件），前向 3 年／5 年
  **含现金分红再投**的年化总回报（送转按股、分红按除权日收盘再投）；
* 分组 = `a_share_watchlist_quality_tiers.csv` 的 2026 年人工分档（**含后视**：今日的 L1 是
  「护城河被后来证明的公司」，故本检验对 L1 只能给**上界**；面板内不在今日池的记为 `NA`）；
* 每组报：样本数、Spearman(P/V, 前向)、对数线性拟合上前向恰等于要求回报的 `P/V`（公允点，
  模型公允时≈1）、各 `P/V` 桶的前向年化中位。

用法::

    python3 scripts/experimental/panel_tier_forward.py \
        --states data/processed/a_share_daily_states_adopted.csv \
        --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --since 2005-01-01
"""
from __future__ import annotations

import argparse
import bisect
import csv
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_historical_valuation_bands as bhv  # noqa: E402
from moat_param_lab import (BUCKETS, forward_annualized, loglinear_fair_pv,  # noqa: E402
                            month_ends, spearman, total_return_index)

TIERS = ROOT / "data/processed/a_share_watchlist_quality_tiers.csv"


def load_spans(path: Path) -> dict[str, list[tuple[str, str]]]:
    spans: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            spans[r["security_code"].zfill(6)].append(
                (r["effective_from"], r.get("effective_to") or "9999-12-31"))
    return dict(spans)


def in_span(spans: list[tuple[str, str]], day: str) -> bool:
    return any(a <= day <= b for a, b in spans)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", type=Path, required=True)
    ap.add_argument("--panel", type=Path, required=True)
    ap.add_argument("--since", default="2005-01-01")
    ap.add_argument("--hurdle", type=float, default=0.10)
    ap.add_argument("--exclude-banks", action="store_true",
                    help="剔除银行（股利折现口径，与 ROIC 口径不可比）")
    ap.add_argument("--per-code-out", type=Path,
                    help="逐票统计落盘（代码/分档/样本数/Spearman/公允 P/V/P/V 中位），供与打分列做相关")
    a = ap.parse_args()

    spans = load_spans(a.panel)
    tiers = {}
    with TIERS.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            tiers[r["security_code"].zfill(6)] = r["quality_tier"]
    names: dict[str, str] = {}
    with TIERS.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            names[r["security_code"].zfill(6)] = r["security_name"]

    # 逐日状态只留面板代码的月末观测（流式读，内存与全市场无关）
    pv_by_code: dict[str, dict[str, float]] = defaultdict(dict)
    with a.states.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        i_code, i_date, i_ratio = (header.index("security_code"), header.index("date"),
                                   header.index("valuation_ratio"))
        for row in reader:
            code = row[i_code].zfill(6)
            if code not in spans or not row[i_ratio]:
                continue
            day = row[i_date]
            if day < a.since or not in_span(spans[code], day):
                continue
            pv_by_code[code][day] = float(row[i_ratio])

    bank_codes = set()
    if a.exclude_banks:
        # 银行识别：名字含「银行」（全词）。
        bank_codes = {c for c, n in names.items() if "银行" in n}

    samples: dict[str, list[tuple[float, float | None, float | None]]] = defaultdict(list)
    per_code: dict[str, list[tuple[float, float | None]]] = defaultdict(list)
    for code, pvs in pv_by_code.items():
        if code in bank_codes:
            continue
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, bhv.load_actions().get(code, []))
        tier = tiers.get(code, "NA")
        for d in month_ends(days):
            pv = pvs.get(d)
            if pv is None:
                continue
            f3 = forward_annualized(tr, days, d, 3)
            f5 = forward_annualized(tr, days, d, 5)
            samples[tier].append((pv, f3, f5))
            per_code[code].append((pv, f3))

    print(f"\n### 分档条件校准（面板 {a.panel.name}，自 {a.since}，月末观测；分档 = 2026 年人工分档，含后视）\n")
    for horizon, idx in (("3 年", 1), ("5 年", 2)):
        print(f"\n**前向 {horizon} 含分红再投年化**\n")
        print("| 分档 | 只数 | n | Spearman | 公允 P/V(前向={:.0%}) | ".format(a.hurdle)
              + " | ".join(f"[{lo:g},{hi:g})" for lo, hi in BUCKETS) + " |")
        print("| --- | ---: | ---: | ---: | ---: | " + " | ".join("---:" for _ in BUCKETS) + " |")
        for tier in ("L1", "L2", "L3", "NA"):
            rows = [(p, s[idx]) for s in samples.get(tier, []) for p in [s[0]] if s[idx] is not None]
            if len(rows) < 10:
                continue
            n_codes = len({c for c, lst in per_code.items() if tiers.get(c, "NA") == tier})
            rho = spearman([p for p, _ in rows], [f for _, f in rows])
            fair = loglinear_fair_pv(rows, a.hurdle)
            cells = []
            for lo, hi in BUCKETS:
                sel = [f for p, f in rows if lo <= p < hi]
                cells.append(f"{statistics.median(sel):+.0%} ({len(sel)})" if len(sel) >= 5 else "—")
            print(f"| {tier} | {n_codes} | {len(rows)} | {rho:+.2f} | "
                  f"{'—' if fair is None else round(fair, 2)} | " + " | ".join(cells) + " |")

    if a.per_code_out:
        with a.per_code_out.open("w", newline="", encoding="utf-8") as fo:
            w = csv.writer(fo)
            w.writerow(["security_code", "security_name", "quality_tier", "n_fwd3",
                        "spearman_fwd3", "fair_pv_fwd3", "median_pv", "share_below_buy"])
            for code in sorted(per_code):
                rows = [(p, f) for p, f in per_code[code] if f is not None]
                allpv = [p for p, _ in per_code[code]]
                rho = spearman([p for p, _ in rows], [f for _, f in rows]) if len(rows) >= 12 else None
                fair = loglinear_fair_pv(rows, a.hurdle) if len(rows) >= 12 else None
                w.writerow([code, names.get(code, ""), tiers.get(code, "NA"), len(rows),
                            "" if rho is None else f"{rho:.3f}", "" if fair is None else f"{fair:.3f}",
                            f"{statistics.median(allpv):.3f}" if allpv else "",
                            f"{sum(1 for p in allpv if p < 0.9407) / len(allpv):.3f}" if allpv else ""])
        print(f"\n逐票统计已写入 {a.per_code_out}")

    # 逐票公允点（只列 L1，供「从特殊到一般」对照）
    print("\n**L1 逐票：样本数、Spearman(P/V, 前向3年)、公允 P/V（前向 3 年 = 要求回报）、P/V 中位**\n")
    print("| 代码 | 名称 | n | Spearman | 公允 P/V | P/V 中位 | P/V<0.9407 占比 |")
    print("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for code in sorted(per_code, key=lambda c: names.get(c, c)):
        if tiers.get(code) != "L1":
            continue
        rows = [(p, f) for p, f in per_code[code] if f is not None]
        allpv = [p for p, _ in per_code[code]]
        if len(rows) < 12:
            print(f"| {code} | {names.get(code, '')} | {len(rows)} | — | — | "
                  f"{statistics.median(allpv):.2f} | {sum(1 for p in allpv if p < 0.9407) / len(allpv):.0%} |")
            continue
        rho = spearman([p for p, _ in rows], [f for _, f in rows])
        fair = loglinear_fair_pv(rows, a.hurdle)
        print(f"| {code} | {names.get(code, '')} | {len(rows)} | {rho:+.2f} | "
              f"{'—' if fair is None else round(fair, 2)} | {statistics.median(allpv):.2f} | "
              f"{sum(1 for p in allpv if p < 0.9407) / len(allpv):.0%} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
