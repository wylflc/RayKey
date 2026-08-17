#!/usr/bin/env python3
"""Regression tests for point-in-time universe interval loading.

Run: ``python3 scripts/test_backtest_universe.py``

The panel format is one row per membership interval.  A backtest therefore
must carry a member forward from ``effective_from`` through ``effective_to``;
grouping only by the start date silently drops long-lived members whenever a
later cohort starts.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest_valuation_strategy import interval_active, load_quota, load_universe  # noqa: E402
from experimental.align_buy_line import load_spans, ratios  # noqa: E402


def members_on(universe: list[tuple[str, set[str]]], day: str) -> set[str]:
    members: set[str] = set()
    for effective_from, snapshot in universe:
        if effective_from > day:
            break
        members = snapshot
    return members


def case_intervals_are_carried_forward() -> list[str]:
    """A long-lived member must survive unrelated later cohort starts."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "panel.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("effective_from", "effective_to", "security_code"),
            )
            writer.writeheader()
            writer.writerows([
                {"effective_from": "2020-01-01", "effective_to": "2020-12-31", "security_code": "A"},
                {"effective_from": "2020-06-01", "effective_to": "", "security_code": "B"},
            ])
        universe = load_universe(path)

    expected = {
        "2020-05-31": {"A"},
        "2020-06-01": {"A", "B"},
        "2020-12-31": {"A", "B"},
        "2021-01-01": {"B"},
    }
    return [
        f"{day}: expected {want}, got {members_on(universe, day)}"
        for day, want in expected.items()
        if members_on(universe, day) != want
    ]


def case_adjacent_intervals_do_not_flicker() -> list[str]:
    """Inclusive intervals sharing a boundary must not drop the member."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "panel.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("effective_from", "effective_to", "security_code"),
            )
            writer.writeheader()
            writer.writerows([
                {"effective_from": "2020-01-01", "effective_to": "2020-06-01", "security_code": "A"},
                {"effective_from": "2020-06-01", "effective_to": "2020-12-31", "security_code": "A"},
            ])
        universe = load_universe(path)

    expected = {
        "2020-06-01": {"A"},
        "2020-06-02": {"A"},
        "2020-12-31": {"A"},
        "2021-01-01": set(),
    }
    return [
        f"{day}: expected {want}, got {members_on(universe, day)}"
        for day, want in expected.items()
        if members_on(universe, day) != want
    ]


def case_alignment_uses_the_same_interval_semantics() -> list[str]:
    """Line alignment must include open intervals and the inclusive end day."""
    with tempfile.TemporaryDirectory() as tmp:
        panel = Path(tmp) / "panel.csv"
        states = Path(tmp) / "states.csv"
        with panel.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("effective_from", "effective_to", "security_code"),
            )
            writer.writeheader()
            writer.writerows([
                {"effective_from": "2020-01-01", "effective_to": "", "security_code": "A"},
                {"effective_from": "2020-01-01", "effective_to": "2020-06-01", "security_code": "B"},
            ])
        with states.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("security_code", "date", "valuation_ratio"),
            )
            writer.writeheader()
            writer.writerows([
                {"security_code": "A", "date": "2021-01-01", "valuation_ratio": "2"},
                {"security_code": "B", "date": "2020-06-01", "valuation_ratio": "3"},
                {"security_code": "B", "date": "2020-06-02", "valuation_ratio": "4"},
            ])
        got = ratios(states, load_spans(panel))
    return [] if got == [2.0, 3.0] else [f"expected [2.0, 3.0], got {got}"]


def case_quota_uses_the_same_interval_semantics() -> list[str]:
    """The optional quota channel must share inclusive/open interval rules."""
    with tempfile.TemporaryDirectory() as tmp:
        panel = Path(tmp) / "panel.csv"
        with panel.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=("effective_from", "effective_to", "security_code"),
            )
            writer.writeheader()
            writer.writerows([
                {"effective_from": "2020-01-01", "effective_to": "", "security_code": "000001"},
                {"effective_from": "2020-01-01", "effective_to": "2020-06-01", "security_code": "000002"},
            ])
        quota = load_quota(panel)

    expected = {
        ("000001", "2021-01-01"): True,
        ("000002", "2020-06-01"): True,
        ("000002", "2020-06-02"): False,
    }
    return [
        f"{code} on {day}: expected {want}, got {interval_active(quota[code], day)}"
        for (code, day), want in expected.items()
        if interval_active(quota[code], day) != want
    ]


CASES = [
    ("interval members carry forward", case_intervals_are_carried_forward),
    ("adjacent intervals do not flicker", case_adjacent_intervals_do_not_flicker),
    ("alignment shares interval semantics", case_alignment_uses_the_same_interval_semantics),
    ("quota shares interval semantics", case_quota_uses_the_same_interval_semantics),
]


def main() -> int:
    failed = 0
    for name, run in CASES:
        problems = run()
        print(f"  {'PASS' if not problems else 'FAIL'}  {name}")
        for problem in problems:
            print(f"        {problem}")
        failed += bool(problems)
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
