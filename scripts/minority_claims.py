"""OI-175: point-in-time facts and a single-count bridge for minority claims.

The registry contains disclosed facts, never a target value or an override of m.
An unresolved contract invalidates earlier usable bands until a complete, dated
reconciliation is supplied. Ordinary companies do not enter the event path.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

EVENTS_FILE = Path(__file__).resolve().parents[1] / "data/reference/minority_claim_events.json"
ROW_FIELDS = ("minority_claim_status", "minority_claim_event", "minority_fixed_claim_ps",
              "minority_dividend_floor_ps")


def number(row: dict, key: str, *, nonnegative: bool = False) -> float:
    value = float(row[key])
    if not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(f"Invalid minority claim fact: {key}")
    return value


def load_events(path: Path = EVENTS_FILE) -> dict[str, list[dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    seen = set()
    event_ids = set()
    for event in raw["events"]:
        code = event["security_code"]
        if len(code) != 6 or not code.isdigit():
            raise ValueError("Invalid security_code in minority claim registry")
        for field in ("effective_date", "known_from", "report_date"):
            date.fromisoformat(event[field])
        if event["effective_date"] > event["known_from"] or event["report_date"] > event["known_from"]:
            raise ValueError("Minority claim facts precede the disclosed event/report")
        if event["status"] not in {"unresolved", "reconciled"}:
            raise ValueError("Unknown minority claim status")
        if not event.get("sources") or not event.get("reason"):
            raise ValueError("Minority claim evidence and reason are required")
        key = (code, event["known_from"])
        identity = event.get("event_id")
        if not isinstance(identity, str) or not identity or identity in event_ids:
            raise ValueError("Minority claim event_id must identify one unique fact version")
        event_ids.add(identity)
        if key in seen:
            raise ValueError("Duplicate minority claim version")
        seen.add(key)
        if event["status"] == "reconciled":
            reconcile(event)  # Fail loudly for malformed claimed-complete input.
        out.setdefault(code, []).append(event)
    for events in out.values():
        events.sort(key=lambda e: e["known_from"])
    return out


@lru_cache(maxsize=1)
def registry() -> dict[str, list[dict]]:
    return load_events()


def event_as_of(code: str, as_of: str, events: dict | None = None) -> dict | None:
    candidates = (registry() if events is None else events).get(code, ())
    return max((e for e in candidates if e["known_from"] <= as_of
                and e["effective_date"] <= as_of), key=lambda e: e["known_from"], default=None)


def blocking_reason(code: str, as_of: str, report_date: str,
                    events: dict | None = None) -> str:
    event = event_as_of(code, as_of, events)
    if event is None:
        return ""
    if event["status"] != "reconciled":
        return "少数股权请求权待核验：" + event["reason"]
    if report_date != event["report_date"]:
        return "少数股权请求权待核验：新报告须补齐同期股权桥快照，不沿用历史份额或旧带"
    return ""


@dataclass(frozen=True)
class ClaimSnapshot:
    shares: float
    total_equity: float
    capital_debt: float
    financial_net_debt: float
    residual_book: float
    residual_share: float
    fixed_claim: float
    dividend_floor: float
    annual_profit: float
    ttm_profit: float | None


def reconcile(event: dict) -> ClaimSnapshot:
    """Map a complete, same-period fact snapshot to non-overlapping claims.

    A subject with fair-value-linked exit consideration cannot be described as
    a fixed redemption. Its contract must be valued separately before this path
    can be used. Explicitly acknowledged fixed redemptions include the interim
    distributions; distributions on continuing interests are a floor, not an
    additional deduction from their perpetual value.
    """
    s = event["snapshot"]
    forbidden = {"m", "minority_share", "ev", "iv", "target_price", "multiple"}
    if forbidden.intersection(s):
        raise ValueError("Valuation overrides are forbidden in claim facts")
    shares = number(s, "shares", nonnegative=True)
    equity = number(s, "total_equity", nonnegative=True)
    parent = number(s, "parent_equity", nonnegative=True)
    debt = number(s, "reported_debt", nonnegative=True)
    cash = number(s, "cash_and_trading_assets", nonnegative=True)
    revenue = number(s, "annual_revenue", nonnegative=True)
    book = number(s, "minority_equity", nonnegative=True)
    profit = number(s, "annual_net_profit")
    minority_profit = number(s, "annual_minority_profit")
    if shares <= 0 or equity <= 0 or profit <= 0:
        raise ValueError("Positive shares, equity and annual consolidated profit required")
    if not math.isclose(parent + book, equity, rel_tol=1e-7, abs_tol=1):
        raise ValueError("Minority claim snapshot equity does not reconcile")
    date.fromisoformat(s["annual_report_date"])
    if not s["annual_report_date"].endswith("-12-31") or s["annual_report_date"] > event["report_date"]:
        raise ValueError("Invalid annual profit basis")
    total_claims = included = fixed = div_floor = subject_book = 0.0
    subjects = set()
    for sub in s["subjects"]:
        if sub["subject"] in subjects:
            raise ValueError("Overlapping minority subject")
        subjects.add(sub["subject"])
        fraction = number(sub, "minority_fraction", nonnegative=True)
        covered = number(sub, "fixed_exit_fraction", nonnegative=True)
        if not 0 <= covered <= fraction <= 1 or fraction == 0:
            raise ValueError("Invalid covered minority fraction")
        if sub["exit_basis"] not in {"fixed", "none"} or (covered > 0 and sub["exit_basis"] != "fixed"):
            raise ValueError("Fair-value/contingent exit cannot erase perpetual minority rights")
        sub_book = number(sub, "minority_equity", nonnegative=True)
        subject_book += sub_book
        liability = number(sub, "redemption_liability", nonnegative=True)
        dividend = number(sub, "dividend_liability", nonnegative=True)
        counted = number(sub, "liability_in_reported_debt", nonnegative=True)
        if counted > liability + dividend + 1 or (covered == 0 and liability > 0):
            raise ValueError("Invalid liability coverage")
        remaining = fraction - covered
        weight = covered / fraction
        book -= sub_book * weight
        minority_profit += (number(sub, "annual_net_profit") * remaining
                            - number(sub, "annual_minority_profit"))
        total_claims += liability + dividend
        included += counted
        fixed += liability + dividend * weight
        div_floor += dividend * (1 - weight)
    if subject_book > number(s, "minority_equity") + 1 or included > debt + 1:
        raise ValueError("Claim facts exceed their balance-sheet parent total")
    ttm_profit = number(s, "ttm_net_profit") if s.get("ttm_net_profit") is not None else None
    return ClaimSnapshot(
        shares, equity, debt + total_claims - included,
        debt - included - max(0.0, cash - 0.02 * revenue),
        max(0.0, book), min(0.95, max(0.0, minority_profit / profit)),
        fixed, div_floor, profit, ttm_profit)


def equity_bridge(ev: float, financial_debt: float, minority_book: float,
                  minority_share: float, external_equity: float = 0.0,
                  fixed_claim: float = 0.0, dividend_floor: float = 0.0
                  ) -> tuple[float, float]:
    """Return total deductions and the fixed component for the thin-equity guard."""
    residual_equity = ev - financial_debt
    floor = max(minority_book, dividend_floor)
    by_profit = minority_share * residual_equity if residual_equity > 0 and minority_share > 0 else 0.0
    minority = max(floor, by_profit)
    deduction = financial_debt + fixed_claim + minority - external_equity
    return deduction, deduction - (by_profit if by_profit > floor else 0.0)


def row_blocked(row: dict) -> bool:
    return row.get("minority_claim_status") == "blocked"


def row_key(row: dict) -> tuple[str, str]:
    return row.get("available_at", ""), row.get("report_date", "")


def state_allowed(row: dict) -> bool:
    event = event_as_of(row.get("security_code", ""), row.get("date", ""))
    return event is None or (event["status"] == "reconciled"
                            and row.get("band_report_date") == event["report_date"]
                            and row.get("minority_claim_event") == event["event_id"])


def invalidate_row(row: dict, as_of: str) -> dict:
    """Protect cached/current readers even when their model file predates an event."""
    code = row.get("security_code", "")
    reason = blocking_reason(code, as_of, row.get("report_date", ""))
    event = event_as_of(code, as_of)
    if not reason and event and (row.get("minority_claim_event") != event["event_id"]
                                or row.get("minority_claim_status") != "reconciled"):
        reason = "少数股权事实已更新，须用对应快照重建模型，不恢复同报告期的旧带"
    if not reason:
        return row
    result = dict(row, status="rejected", reason=reason, minority_claim_status="blocked",
                  minority_claim_event=event["event_id"])
    result["available_at"] = max(result.get("available_at", ""), event["known_from"])
    result["report_date"] = max(result.get("report_date", ""), event["report_date"])
    for key in ("intrinsic_value", "band_low", "band_high", "max_buy_price", "v_bear", "v_bull", "v_zero_growth"):
        if key not in result:
            continue
        result[key] = ""
    return result
