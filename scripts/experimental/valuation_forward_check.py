#!/usr/bin/env python3
"""Test whether an absolute P/V ratio predicts later returns across the PIT panel.

The check is deliberately independent of portfolio rules.  It takes the last
in-panel valuation observation of each company-year, measures the following
three-year split-adjusted price return, and reports:

- overall and per-year Spearman correlation between P/V and forward return;
- P/V deciles formed separately inside each sample year;
- the cheapest-minus-richest decile spread.

Cash dividends are not included, matching ``roic_anchor_check.py``.  This
understates the forward return of high-dividend companies and must be stated
with any result.

Example:
    python3 scripts/experimental/valuation_forward_check.py \
      --states data/processed/a_share_daily_states_adopted.csv \
      --panel data/processed/pit_attention/panel_moat_bank_v6b.csv
"""

from __future__ import annotations

import argparse
import bisect
import csv
import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_historical_valuation_bands as bhv  # noqa: E402


def load_spans(path: Path) -> dict[str, list[tuple[str, str]]]:
    spans: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            spans[row["security_code"].zfill(6)].append(
                (row["effective_from"], row.get("effective_to") or "9999-12-31")
            )
    return dict(spans)


def active(spans: list[tuple[str, str]], day: str) -> bool:
    return any(start <= day <= end for start, end in spans)


def add_years(day: str, years: int) -> str:
    value = date.fromisoformat(day)
    try:
        return value.replace(year=value.year + years).isoformat()
    except ValueError:  # February 29
        return value.replace(year=value.year + years, day=28).isoformat()


def average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        stop = cursor + 1
        while stop < len(order) and values[order[stop]] == values[order[cursor]]:
            stop += 1
        rank = (cursor + stop - 1) / 2
        for position in range(cursor, stop):
            ranks[order[position]] = rank
        cursor = stop
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float:
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerator = sum((x - mx) * (y - my) for x, y in zip(rx, ry))
    denominator = (
        sum((x - mx) ** 2 for x in rx) * sum((y - my) ** 2 for y in ry)
    ) ** 0.5
    return numerator / denominator if denominator else float("nan")


def evaluate_company(
    code: str,
    annual: dict[str, tuple[str, float, float]],
    actions: dict[str, list[dict]],
    horizon: int,
) -> list[tuple[str, str, float, float]]:
    prices = bhv.load_ohlcv(code)
    if not prices:
        return []
    days = [day for day, _close in prices]
    closes = [close for _day, close in prices]
    out = []
    for year, (sample_day, ratio, close) in annual.items():
        target = add_years(sample_day, horizon)
        index = bisect.bisect_right(days, target) - 1
        if index < 0 or (
            date.fromisoformat(target) - date.fromisoformat(days[index])
        ).days > 62:
            # Require a price close to the target, rather than silently turning
            # a three-year test into a much shorter return after a long halt.
            continue
        factor = bhv.split_factor(actions.get(code, []), sample_day, days[index])
        total_return = closes[index] * factor / close - 1
        if total_return <= -1:
            continue
        annualized = (1 + total_return) ** (1 / horizon) - 1
        out.append((year, code, ratio, annualized))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--states", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--since", default="2009-11-01")
    parser.add_argument("--horizon", type=int, default=3)
    args = parser.parse_args()

    spans = load_spans(args.panel)
    actions = bhv.load_actions()
    observations: list[tuple[str, str, float, float]] = []
    current_code = ""
    annual: dict[str, tuple[str, float, float]] = {}

    def flush() -> None:
        nonlocal annual
        if current_code and annual:
            observations.extend(evaluate_company(current_code, annual, actions, args.horizon))
        annual = {}

    with args.states.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            code = row["security_code"].zfill(6)
            if code != current_code:
                flush()
                current_code = code
            day = row["date"]
            if day < args.since or not active(spans.get(code, []), day):
                continue
            try:
                ratio = float(row["valuation_ratio"])
                close = float(row["close"])
            except (TypeError, ValueError):
                continue
            if ratio > 0 and close > 0:
                annual[day[:4]] = (day, ratio, close)
    flush()

    by_year: dict[str, list[tuple[str, str, float, float]]] = defaultdict(list)
    for row in observations:
        by_year[row[0]].append(row)
    usable_years = {year: rows for year, rows in by_year.items() if len(rows) >= 20}
    if not usable_years:
        print("No sample year has at least 20 forward observations", file=sys.stderr)
        return 1

    pooled = [row for rows in usable_years.values() for row in rows]
    overall = spearman([row[2] for row in pooled], [row[3] for row in pooled])
    yearly_rho = [
        spearman([row[2] for row in rows], [row[3] for row in rows])
        for rows in usable_years.values()
    ]

    deciles: dict[int, list[tuple[str, str, float, float]]] = defaultdict(list)
    for rows in usable_years.values():
        ordered = sorted(rows, key=lambda row: row[2])
        for index, row in enumerate(ordered):
            deciles[min(9, index * 10 // len(ordered))].append(row)

    print(
        f"observations={len(pooled):,} companies={len({row[1] for row in pooled})} "
        f"sample_years={len(usable_years)} horizon={args.horizon}y"
    )
    print(f"overall_spearman={overall:+.4f}")
    print(
        f"yearly_spearman_median={statistics.median(yearly_rho):+.4f} "
        f"negative_years={sum(rho < 0 for rho in yearly_rho)}/{len(yearly_rho)}"
    )
    print("decile|n|median_pv|median_forward_cagr|positive_share")
    for decile in range(10):
        rows = deciles[decile]
        print(
            f"D{decile + 1}|{len(rows)}|{statistics.median(row[2] for row in rows):.4f}|"
            f"{statistics.median(row[3] for row in rows):+.4%}|"
            f"{sum(row[3] > 0 for row in rows) / len(rows):.1%}"
        )
    spread = statistics.median(row[3] for row in deciles[0]) - statistics.median(
        row[3] for row in deciles[9]
    )
    print(f"D1_minus_D10_median_cagr={spread:+.4%}")
    print("cash_dividends_included=no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
