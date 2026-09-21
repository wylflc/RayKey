"""Independent distribution components and same-day events (workflow §8.3).

Keep fiscal/availability metadata on components. Daily actual entitlements and
exchange price terms are separate; both refer to the pre-event share basis.
"""
from __future__ import annotations

from collections import defaultdict
import csv
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Iterable

ACTION_FIELDS = ["security_code", "security_name", "ex_dividend_date", "cash_per_share",
                 "share_ratio", "plan", "report_date", "plan_notice_date", "progress",
                 "rights_ratio", "rights_price"]
AMOUNTS = ("cash_per_share", "share_ratio", "rights_ratio", "rights_price")
COMPONENT_EXCLUSIONS = Path(__file__).resolve().parents[1] / 'data/reference/a_share_action_component_exclusions.csv'
PRICE_TERMS_PATH = COMPONENT_EXCLUSIONS.with_name('a_share_exright_terms.csv')
COMPONENT_CORRECTIONS = COMPONENT_EXCLUSIONS.with_name('a_share_action_component_corrections.csv')
PRICE_FIELDS = tuple('price_' + k for k in AMOUNTS)


class CorporateAction(tuple):
    """Four actual entitlement amounts, with separate exchange price parameters.

    Iteration retains the cash/share accounting contract. Price consumers must
    call price_terms. Pickling retains both bases for multiprocessing backtests.
    """
    def __new__(cls, actual, price=None):
        obj = super().__new__(cls, actual)
        if len(obj) != 4:
            raise ValueError('Corporate action requires four actual amounts')
        obj.price = tuple(obj if price is None else price)
        if len(obj.price) != 4:
            raise ValueError('Corporate action requires four price amounts')
        return obj

    def __getnewargs__(self):
        return tuple(self), self.price


def price_terms(event):
    return getattr(event, 'price', event)


def event_from_row(row):
    actual = tuple(float(amount(row, k)) for k in AMOUNTS)
    present = [row.get(k) not in (None, '') for k in PRICE_FIELDS]
    if any(present) and not all(present):
        raise ValueError('Incomplete exchange price terms')
    price = tuple(float(number(row[p], share_change=k == 'share_ratio'))
                  for k, p in zip(AMOUNTS, PRICE_FIELDS)) if all(present) else actual
    return CorporateAction(actual, price)


@lru_cache(maxsize=8)
def _price_overrides(path, mtime, size):
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        return validate_price_overrides(csv.DictReader(handle))


def validate_price_overrides(rows):
    rules = {}
    for row in rows:
        key = row['security_code'], row['ex_dividend_date']
        if key in rules or not row.get('source_url') or not row.get('source_pages'):
            raise ValueError(f'Invalid/duplicate exchange price terms: {key}')
        if not row.get('notice_date') or row['notice_date'] > key[1]:
            raise ValueError(f'Exchange terms unavailable at ex date: {key}')
        event_from_row(row)  # Validate both complete numeric bases.
        if any(row.get(k) in (None, '') for k in (*AMOUNTS, *PRICE_FIELDS)):
            raise ValueError(f'Incomplete verified exchange terms: {key}')
        rules[key] = row
    return rules


def price_overrides():
    path = PRICE_TERMS_PATH
    if path is None or not path.exists():
        return {}
    stat = path.stat()
    return _price_overrides(str(path), stat.st_mtime_ns, stat.st_size)


def with_price_terms(row, *, overrides=None):
    """Enrich a daily aggregate; never distribute a daily override over components."""
    rule = (price_overrides() if overrides is None else overrides).get((row['security_code'], row['ex_dividend_date']))
    if rule:
        for k in AMOUNTS:
            if abs(amount(row, k) - amount(rule, k)) > Decimal('0.0000000001'):
                raise ValueError(f'Actual distribution changed under verified price terms: '
                                 f'{row["security_code"]} {row["ex_dividend_date"]} {k}')
    return {**row, **{p: float(rule[p]) if rule else row[k] for k, p in zip(AMOUNTS, PRICE_FIELDS)},
            'price_terms_source': rule['source_url'] if rule else 'unverified_actual_fallback'}


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


def correct_components(rows, path=COMPONENT_CORRECTIONS):
    """Apply issuer-verified source errors; accept already corrected refreshes."""
    rules = {}
    if path.exists():
        with path.open(newline='', encoding='utf-8-sig') as handle:
            for rule in csv.DictReader(handle):
                key = action_key(rule)
                if key in rules or not rule.get('source_url') or not rule.get('reason'):
                    raise ValueError(f'Invalid component correction: {key}')
                rules[key] = rule
    result = []
    for row in unique_actions(rows):
        rule = rules.get(action_key(row))
        if rule:
            actual = tuple(amount(row, k) for k in AMOUNTS)
            expected = tuple(number(rule['expected_' + k], share_change=k == 'share_ratio') for k in AMOUNTS)
            corrected = tuple(amount(rule, k) for k in AMOUNTS)
            if actual not in (expected, corrected):
                raise ValueError(f'Corrected source component changed: {action_key(row)}')
            row = {**row, **{k: rule[k] for k in AMOUNTS}, 'plan': rule['plan']}
        result.append(row)
    return result


@lru_cache(maxsize=8)
def _accounting_overrides(path, mtime, size):
    with Path(path).open(newline='', encoding='utf-8-sig') as handle:
        return {action_key(r): str(number(r['accounting_cash_per_share']))
                for r in csv.DictReader(handle) if r.get('accounting_cash_per_share')}


def accounting_cash(row):
    """Company equity bridge: use weighted total for unequal shareholder classes."""
    if not row.get('security_code'):
        return row.get('cash_per_share', '')
    path = COMPONENT_CORRECTIONS
    if path.exists():
        stat = path.stat()
        value = _accounting_overrides(str(path), stat.st_mtime_ns, stat.st_size).get(action_key(row))
        if value is not None:
            return value
    return row.get('cash_per_share', '')


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
    return correct_components(kept)


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
    overrides = price_overrides()
    for row in aggregate_actions(rows):
        row = with_price_terms(row, overrides=overrides)
        if not include_rights:
            for k in ('rights_ratio', 'rights_price', 'price_rights_ratio', 'price_rights_price'):
                row[k] = 0.
        if not any(row[k] for k in AMOUNTS[:3]):
            continue
        out[row["security_code"]][row["ex_dividend_date"]] = event_from_row(row)
    return out


def company_events(rows: Iterable[dict], *, price_basis: bool = False) -> list[dict]:
    """Aggregate an already selected company's component list (code may be omitted)."""
    events = aggregate_actions(({**r, "security_code": r.get("security_code") or "_company"} for r in rows))
    # Valuation helpers consume the same textual-number schema as the CSV.
    if price_basis:
        overrides = price_overrides()
        events = [with_price_terms(r, overrides=overrides) for r in events]
    return [{**r, **{k: str(r['price_' + k] if price_basis else r[k]) for k in AMOUNTS}} for r in events]
