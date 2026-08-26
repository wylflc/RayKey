#!/usr/bin/env python3
"""A-share production signal/evidence date mapping.

The daily workflow accepts one date only: the signal date.  Report evidence is
cut off at the next workday, defined here as the first Monday-Friday date after
the signal date.  Keep this tiny module dependency-free so every production
stage and its regression tests use exactly the same mapping.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta


def next_workday(signal_date: date) -> date:
    """Return the first Monday-Friday date strictly after ``signal_date``."""
    candidate = signal_date + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def evidence_date_for_signal(signal_date: str | date) -> date:
    """Parse a signal date when needed and return its fixed evidence date."""
    parsed = date.fromisoformat(signal_date) if isinstance(signal_date, str) else signal_date
    return next_workday(parsed)


def evidence_iso_for_signal(signal_date: str | date) -> str:
    return evidence_date_for_signal(signal_date).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="由 A 股信号日推导唯一证据日")
    parser.add_argument("--signal-date", required=True, help="信号日 YYYY-MM-DD")
    args = parser.parse_args()
    print(evidence_iso_for_signal(args.signal_date))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
