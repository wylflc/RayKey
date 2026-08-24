#!/usr/bin/env python3
"""按 §11.4 把一次除权除息／配股落到持仓表，并登记「已处理」台账（防漏调与重复除权）。

用法::

    # 事件取自事件库（配股）或东财当日接口（分红送转）
    python3 scripts/apply_holdings_corporate_action.py --as-of 2026-08-25 --code 600036
    # 差异化分派等价格口径与公告不一致时，显式给每股现金／送转／配股
    python3 scripts/apply_holdings_corporate_action.py --as-of 2026-08-25 --code 689009 --cash 1.22 --ratio 0
    python3 scripts/apply_holdings_corporate_action.py --as-of 2026-08-25 --code 600036 --dry-run

规则（§11.4）：`cost_basis`／`entry_stop_price` ← `(原值 − D + r×p) ÷ (1 + k + r)`；`current_shares` ← `× (1 + k)`，
配股认购（缺省认购，`--no-subscribe` 不认购）再 `× (1 + r)`。同一 (代码, 除权日) 已登记即拒绝再次执行。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_a_share_dividends import adjust_for_ex_dividend  # noqa: E402
from workflow_decision_log import DEFAULT_DECISION_LOG, WORKFLOW_VERSION, append_decision_log  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOLDINGS = ROOT / "data/processed/a_share_holdings.csv"
DEFAULT_LEDGER = ROOT / "data/processed/holdings_corporate_actions_applied.csv"
DEFAULT_ACTIONS = ROOT / "data/raw/corporate_actions/a_share_corporate_actions.csv"
HOLDING_FIELDS = ["security_code", "security_name", "current_shares", "cost_basis", "entry_stop_price"]
LEDGER_FIELDS = ["security_code", "security_name", "ex_dividend_date", "cash_per_share", "share_ratio",
                 "rights_ratio", "rights_price", "subscribed", "shares_before", "shares_after",
                 "cost_before", "cost_after", "stop_before", "stop_after", "source", "applied_at_utc", "note"]


def _num(value: object) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_ledger(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def ledger_index(rows: list[dict[str, str]]) -> set[tuple[str, str]]:
    return {(r["security_code"].zfill(6), (r.get("ex_dividend_date") or "")[:10]) for r in rows}


def event_from_actions(path: Path, code: str, as_of: str) -> dict[str, float] | None:
    """事件库当日行（分红送转＋配股合并）；无行返回 None。"""
    if not path.exists():
        return None
    cash = ratio = rr = rp = 0.0
    found = False
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for a in csv.DictReader(fh):
            if str(a.get("security_code") or "").zfill(6) != code or (a.get("ex_dividend_date") or "")[:10] != as_of:
                continue
            found = True
            cash += _num(a.get("cash_per_share")) or 0.0
            ratio = (1 + ratio) * (1 + (_num(a.get("share_ratio")) or 0.0)) - 1
            r = _num(a.get("rights_ratio")) or 0.0
            if r > 0:
                rr += r
                rp = _num(a.get("rights_price")) or rp
    return {"cash": cash, "ratio": ratio, "rights_ratio": rr, "rights_price": rp} if found else None


def event_from_eastmoney(code: str, as_of: str, timeout: float) -> dict[str, float] | None:
    from fetch_a_share_dividends import fetch_ex_dividend_events
    events = fetch_ex_dividend_events(as_of, timeout=timeout)
    ev = events.get(code)
    if not ev:
        return None
    return {"cash": float(ev["cash_per_share"]), "ratio": float(ev["share_ratio"]),  # type: ignore[arg-type]
            "rights_ratio": 0.0, "rights_price": 0.0}


def apply_action(holdings_path: Path, ledger_path: Path, log_path: Path | None, code: str, as_of: str,
                 cash: float, ratio: float, rights_ratio: float, rights_price: float,
                 subscribe: bool, source: str, note: str = "", dry_run: bool = False) -> dict[str, object]:
    code = code.zfill(6)
    ledger = load_ledger(ledger_path)
    if (code, as_of) in ledger_index(ledger):
        raise SystemExit(f"拒绝：{code} {as_of} 已在台账 {ledger_path.name} 登记，再执行即重复除权")
    with holdings_path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    row = next((r for r in rows if str(r["security_code"]).zfill(6) == code), None)
    if row is None:
        raise SystemExit(f"拒绝：{code} 不在持仓表 {holdings_path.name}")
    shares0 = _num(row.get("current_shares")) or 0.0
    cost0, stop0 = _num(row.get("cost_basis")), _num(row.get("entry_stop_price"))
    denom_shares = (1 + ratio) * ((1 + rights_ratio) if (subscribe and rights_ratio) else 1.0)
    shares1 = shares0 * denom_shares
    cost1 = adjust_for_ex_dividend(cost0, cash, ratio, rights_ratio, rights_price) if cost0 is not None else None
    stop1 = adjust_for_ex_dividend(stop0, cash, ratio, rights_ratio, rights_price) if stop0 is not None else None
    result = {"security_code": code, "security_name": row.get("security_name", ""), "ex_dividend_date": as_of,
              "cash_per_share": f"{cash:g}", "share_ratio": f"{ratio:g}", "rights_ratio": f"{rights_ratio:g}",
              "rights_price": f"{rights_price:g}", "subscribed": "1" if (subscribe and rights_ratio) else "",
              "shares_before": f"{shares0:g}", "shares_after": f"{shares1:g}",
              "cost_before": "" if cost0 is None else f"{cost0:g}", "cost_after": "" if cost1 is None else f"{cost1:.4f}",
              "stop_before": "" if stop0 is None else f"{stop0:g}", "stop_after": "" if stop1 is None else f"{stop1:.4f}",
              "source": source, "applied_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note}
    if dry_run:
        return result
    row["current_shares"] = f"{shares1:g}"
    if cost1 is not None:
        row["cost_basis"] = f"{cost1:.4f}"
    if stop1 is not None:
        row["entry_stop_price"] = f"{stop1:.4f}"
    with holdings_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HOLDING_FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in HOLDING_FIELDS} for r in rows)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not ledger_path.exists() or ledger_path.stat().st_size == 0
    with ledger_path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(result)
    if log_path is not None:
        append_decision_log(log_path, [{
            "logged_at_utc": result["applied_at_utc"], "workflow_stage": "holdings_tracking",
            "run_id": f"corporate_action_{as_of}", "as_of": as_of, "security_code": code,
            "security_name": result["security_name"], "decision_type": "corporate_action_applied",
            "decision_result": "applied",
            "summary_reason": (f"§11.4 除权：现金 {cash:g}/送转 {ratio:g}/配股 {rights_ratio:g}@{rights_price:g}"
                               f"｜股数 {shares0:g}→{shares1:g}｜均价 {result['cost_before'] or 'NA'}→{result['cost_after'] or 'NA'}"
                               f"｜止损锚 {result['stop_before'] or 'NA'}→{result['stop_after'] or 'NA'}｜来源 {source}"),
            "input_files": str(holdings_path), "source_urls": "", "output_file": f"{holdings_path}; {ledger_path}",
            "operator_or_script": "apply_holdings_corporate_action.py", "workflow_version": WORKFLOW_VERSION,
            "decision_id": f"corporate_action:{as_of}:{code}:01", "supersedes_decision_id": ""}])
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--as-of", required=True, help="除权除息日 YYYY-MM-DD")
    ap.add_argument("--code", required=True)
    ap.add_argument("--cash", type=float, help="每股现金红利（价格口径；差异化分派时显式给）")
    ap.add_argument("--ratio", type=float, help="每股送转比例")
    ap.add_argument("--rights-ratio", type=float, help="每股配股数")
    ap.add_argument("--rights-price", type=float, help="配股价")
    ap.add_argument("--no-subscribe", action="store_true", help="配股不认购（股数不按配股放大）")
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--holdings", type=Path, default=DEFAULT_HOLDINGS)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--actions", type=Path, default=DEFAULT_ACTIONS)
    ap.add_argument("--log-file", type=Path, default=DEFAULT_DECISION_LOG)
    ap.add_argument("--timeout", type=float, default=15.0)
    args = ap.parse_args()
    code = args.code.zfill(6)
    explicit = any(v is not None for v in (args.cash, args.ratio, args.rights_ratio, args.rights_price))
    if explicit:
        ev = {"cash": args.cash or 0.0, "ratio": args.ratio or 0.0,
              "rights_ratio": args.rights_ratio or 0.0, "rights_price": args.rights_price or 0.0}
        source = "explicit"
    else:
        ev = event_from_actions(args.actions, code, args.as_of)
        source = "corporate_actions.csv"
        if ev is None:
            try:
                ev = event_from_eastmoney(code, args.as_of, args.timeout)
                source = "eastmoney:RPT_SHAREBONUS_DET"
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(f"事件库无 {code} {args.as_of} 行且东财查询失败（{type(exc).__name__}）：请显式给 --cash/--ratio") from exc
        if ev is None:
            raise SystemExit(f"事件库与东财均无 {code} {args.as_of} 的除权记录：请核对日期或显式给 --cash/--ratio")
    result = apply_action(args.holdings, args.ledger, None if args.dry_run else args.log_file, code, args.as_of,
                          ev["cash"], ev["ratio"], ev["rights_ratio"], ev["rights_price"],
                          not args.no_subscribe, source, args.note, args.dry_run)
    tag = "（dry-run，未写回）" if args.dry_run else "（已写回持仓表并登记台账）"
    print(f"{result['security_name']}（{code}）{args.as_of} 除权{tag}：来源 {source}｜现金 {ev['cash']:g}/送转 {ev['ratio']:g}"
          f"/配股 {ev['rights_ratio']:g}@{ev['rights_price']:g}")
    print(f"  股数 {result['shares_before']} → {result['shares_after']}｜均价 {result['cost_before'] or 'NA'} → {result['cost_after'] or 'NA'}"
          f"｜止损锚 {result['stop_before'] or 'NA'} → {result['stop_after'] or 'NA'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
