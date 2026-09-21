"""Independent distribution components and same-day events (workflow §8.3).

Keep fiscal/availability metadata on components. Only price/share/cash consumers
use the daily aggregate: all ratios on one date refer to the pre-event shares.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

ACTION_FIELDS = ["security_code", "security_name", "ex_dividend_date", "cash_per_share",
                 "share_ratio", "plan", "report_date", "plan_notice_date", "progress",
                 "rights_ratio", "rights_price"]
AMOUNTS = ("cash_per_share", "share_ratio", "rights_ratio", "rights_price")
COMPONENT_EXCLUSIONS = Path(__file__).resolve().parents[1] / 'data/reference/a_share_action_component_exclusions.csv'


def number(value, *, share_change: bool = False) -> Decimal:
    try:
        result = Decimal(str(value or 0))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid corporate-action number: {value!r}") from exc
    if not result.is_finite() or (result <= -1 if share_change else result < 0):
        raise ValueError(f"Invalid corporate-action number: {value!r}")
    return result


def amount(row, key):
    # The shared backtest loader also reads overseas reverse splits.
    return number(row.get(key), share_change=key == 'share_ratio')


def action_key(row: dict) -> tuple[str, str, str, str, str]:
    """A report/announcement identifies a plan; the ex date distinguishes instalments.

    Legacy events without fiscal metadata use their ex date and type. A cash
    dividend and a split can be separate rows in non-A-share input files.
    """
    code = str(row.get("security_code") or "").strip()
    if not code:
        raise ValueError("Corporate action without security_code")
    ex = str(row.get("ex_dividend_date") or "").strip()[:10]
    report = str(row.get("report_date") or "").strip()[:10]
    notice = str(row.get("plan_notice_date") or "").strip()[:10]
    kind = "rights" if number(row.get("rights_ratio")) else "distribution"
    if not report and not notice and kind == "distribution":
        kind = "cash_split" if number(row.get("cash_per_share")) and amount(row, "share_ratio") else (
            "split" if amount(row, "share_ratio") else "cash")
    if not ex and not notice:
        raise ValueError(f"Corporate action without event or plan identity: {code}")
    return code, ex, kind, report, notice


def unique_actions(rows: Iterable[dict]) -> list[dict]:
    """Remove duplicate components, fail on conflicting amounts, independent of order."""
    by_key: dict[tuple, dict] = {}
    for source in rows:
        row = dict(source)
        key = action_key(row)
        amounts = tuple(amount(row, k) for k in AMOUNTS)
        previous = by_key.get(key)
        if previous is not None:
            if amounts != tuple(amount(previous, k) for k in AMOUNTS):
                raise ValueError(f"Conflicting corporate-action component {key}")
            # Numeric facts agree; keep metadata deterministically rather than
            # allowing source page/order changes to alter stored output.
            row = max((previous, row), key=lambda r: tuple(str(r.get(k) or "") for k in ACTION_FIELDS))
        by_key[key] = row
    return [by_key[k] for k in sorted(by_key)]


def merge_actions(existing: Iterable[dict], fresh: Iterable[dict],
                  refreshed_codes: set[str] | None = None) -> list[dict]:
    """Replace successfully refetched dividend histories; retain rights and failures.

    Callers only mark codes whose complete nonempty dividend query succeeded.
    This also removes a stale proposal after implementation or cancellation.
    """
    fresh = unique_actions(fresh)
    refreshed_codes = ({r["security_code"] for r in fresh if not number(r.get("rights_ratio"))}
                       if refreshed_codes is None else refreshed_codes)
    kept = [r for r in existing if r["security_code"] not in refreshed_codes or number(r.get("rights_ratio"))]
    merged = {action_key(r): r for r in unique_actions(kept)}
    merged.update({action_key(r): r for r in fresh})
    return [merged[k] for k in sorted(merged)]


def normalize_eastmoney(rows: Iterable[dict], exclusions_path: Path = COMPONENT_EXCLUSIONS) -> list[dict]:
    out = []
    for row in rows:
        cash = number(row.get("PRETAX_BONUS_RMB")) / 10
        shares = (number(row.get("BONUS_RATIO")) + number(row.get("IT_RATIO"))) / 10
        if not cash and not shares:
            continue
        ex = str(row.get("EX_DIVIDEND_DATE") or "")[:10]
        notice = str(row.get("PLAN_NOTICE_DATE") or "")[:10]
        if not ex and not notice:
            continue
        code = str(row.get("SECURITY_CODE") or "").strip()
        if not code:
            raise ValueError("Eastmoney distribution without code")
        out.append(dict(security_code=code.zfill(6), security_name=row.get("SECURITY_NAME_ABBR") or "",
                        ex_dividend_date=ex, cash_per_share=f"{cash:.6f}", share_ratio=f"{shares:.6f}",
                        plan=row.get("IMPL_PLAN_PROFILE") or "", report_date=str(row.get("REPORT_DATE") or "")[:10],
                        plan_notice_date=notice, progress=row.get("ASSIGN_PROGRESS") or "",
                        rights_ratio="", rights_price=""))
    exclusions = {}
    if exclusions_path.exists():
        with exclusions_path.open(newline='', encoding='utf-8-sig') as handle:
            for rule in csv.DictReader(handle):
                key = tuple(rule[k] for k in ('security_code', 'ex_dividend_date', 'report_date', 'plan_notice_date'))
                if key in exclusions or not rule.get('source_url') or not rule.get('reason'):
                    raise ValueError('Invalid component exclusion')
                exclusions[key] = rule
    kept = []
    for row in unique_actions(out):
        key = tuple(row[k] for k in ('security_code', 'ex_dividend_date', 'report_date', 'plan_notice_date'))
        rule = exclusions.get(key)
        if rule:
            if any(number(row[k]) != number(rule[k]) for k in ('cash_per_share', 'share_ratio')):
                raise ValueError(f'Excluded source component changed: {key}')
            continue
        kept.append(row)
    return kept


def aggregate_actions(rows: Iterable[dict], include_rights: bool = True) -> list[dict]:
    """One event per (code, ex date), summed on the same pre-event share basis."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in unique_actions(rows):
        ex = str(row.get("ex_dividend_date") or "")[:10]
        if ex:
            groups[row["security_code"], ex].append(row)
    out = []
    for (code, ex), group in sorted(groups.items()):
        cash = sum((number(r.get("cash_per_share")) for r in group), Decimal(0))
        shares = sum((amount(r, "share_ratio") for r in group), Decimal(0))
        rights = sum((number(r.get("rights_ratio")) for r in group), Decimal(0)) if include_rights else Decimal(0)
        paid = sum((number(r.get("rights_ratio")) * number(r.get("rights_price")) for r in group), Decimal(0)) if include_rights else Decimal(0)
        if not cash and not shares and not rights:
            continue
        if 1 + shares + rights <= 0:
            raise ValueError(f'Nonpositive share factor: {code} {ex}')
        out.append(dict(security_code=code, ex_dividend_date=ex, cash_per_share=float(cash),
                        share_ratio=float(shares), rights_ratio=float(rights),
                        rights_price=float(paid / rights) if rights else 0.0,
                        security_name=next((r.get("security_name", "") for r in group if r.get("security_name")), ""),
                        plan="；".join(sorted({str(r["plan"]) for r in group if r.get("plan")})),
                        progress="；".join(sorted({str(r["progress"]) for r in group if r.get("progress")}))))
    return out


def event_map(rows: Iterable[dict], include_rights: bool = True) -> dict[str, dict[str, tuple]]:
    out: dict[str, dict[str, tuple]] = defaultdict(dict)
    for row in aggregate_actions(rows, include_rights=include_rights):
        out[row["security_code"]][row["ex_dividend_date"]] = tuple(row[k] for k in AMOUNTS)
    return out


def company_events(rows: Iterable[dict]) -> list[dict]:
    """Aggregate an already selected company's component list (code may be omitted)."""
    events = aggregate_actions(({**r, "security_code": r.get("security_code") or "_company"} for r in rows))
    # Valuation helpers consume the same textual-number schema as the CSV.
    return [{**r, **{k: str(r[k]) for k in AMOUNTS}} for r in events]
