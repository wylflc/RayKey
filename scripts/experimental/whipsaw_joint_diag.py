#!/usr/bin/env python3
"""Event and portfolio diagnostics; forward returns are analysis labels, never inputs."""
from __future__ import annotations

import argparse
import csv
import json
import math
import shlex
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from swap_chop_guard import ChopConfig, ChopGuard
from whipsaw_swap_diag import Market, classify, read_ledger, swap_sells, contrib_by_code
import backtest_valuation_strategy as bt


def median(values):
    good = [x for x in values if x is not None and math.isfinite(x)]
    return statistics.median(good) if good else None


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def config_from_extra(extra):
    args = shlex.split(extra)
    cfg = {}
    fields = {"mode": str, "depth": float, "days": int, "slope": float, "crosses": int,
              "cooldown": int, "progress": float}
    for key, convert in fields.items():
        flag = f"--swap-chop-{key}"
        if flag in args:
            cfg[key] = convert(args[args.index(flag) + 1])
    return ChopConfig(**cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase")
    args = ap.parse_args()
    exp = ROOT / "data/experiments/exp_whipsaw_joint"
    work = exp / args.phase / "bt2011"
    cases = {label.strip(): config_from_extra(extra) for line in (exp / "configs" / f"{args.phase}.txt").read_text().splitlines()
             if line.strip() and not line.startswith("#") for label, extra in [line.split("|", 1)]}
    ledgers = {label: read_ledger(work / label / "ledger.csv") for label in cases}
    blocks = {label: read_ledger(work / label / "blocked.csv") for label in cases}
    codes = {r["security_code"] for rows in ledgers.values() for r in rows}
    codes |= {r[k] for rows in blocks.values() for r in rows for k in ("source_code", "trigger_code")}
    codes.add("002714")
    mk = Market(codes)
    guard = ChopGuard(ChopConfig("flat"), mk.raw, mk.ma, bt.load_actions())
    base = ledgers["BASE"]
    base_swaps = {(r["date"], r["security_code"]): r for r in swap_sells(base)}
    base_buys = defaultdict(list)
    for r in base:
        if r["action"] == "买入":
            base_buys[r["date"]].append(r)
    # Every blocked event gets both the nominal trigger and BASE's actual daily buy basket.
    # The latter is a cash-flow proxy: cash is fungible, so this is NOT exact causal allocation.
    events, summaries, contributions, annual, first_changes = [], [], [], [], []
    base_contrib = contrib_by_code(next((work / "BASE").glob("*_trades.csv")))
    for label, cfg in cases.items():
        if label == "BASE":
            continue
        rows = ledgers[label]
        sales = defaultdict(list)
        for r in rows:
            if r["action"] == "卖出":
                sales[r["security_code"]].append(r)
        start = len(events)
        for r in blocks[label]:
            c, d, s, trigger = r["source_code"], r["exec_date"], r["signal_date"], r["trigger_code"]
            ft = guard.features(c, s) or {}
            category, forward = classify(mk, c, d)
            subsequent = next((t for t in sales[c] if t["date"] >= d), None)
            basket = base_buys[d]
            basket_returns = {}
            for h in (20, 60):
                obs = [(float(t["amount"]), mk.fwd(t["security_code"], d, h)) for t in basket]
                valid = [(a, v) for a, v in obs if math.isfinite(v)]
                # Missing any receiver's horizon means a censored basket, not zero performance.
                basket_returns[h] = (sum(a * v for a, v in valid) / sum(a for a, v in valid)
                                     if valid and len(valid) == len(obs) else float("nan"))
            matched = base_swaps.get((d, c))
            item = dict(arm=label, signal_date=s, exec_date=d, source=c, trigger=trigger,
                        base_matched=bool(matched), base_amount=float(matched["amount"]) if matched else 0,
                        classification=category, source20=forward[20], source60=forward[60],
                        min20=forward["min20"] if math.isfinite(forward[20]) else float("nan"),
                        recovery_days=forward["back"], trigger20=mk.fwd(trigger, d, 20),
                        trigger60=mk.fwd(trigger, d, 60), basket20=basket_returns[20], basket60=basket_returns[60],
                        source_minus_basket20=forward[20] - basket_returns[20],
                        source_minus_basket60=forward[60] - basket_returns[60],
                        next_sale=subsequent["date"] if subsequent else "",
                        next_sale_reason=subsequent["reason"] if subsequent else "",
                        next_source=r["next_source"], reason=r["block_reason"],
                        same_day_source_sale=bool(subsequent and subsequent["date"] == d),
                        gap=ft.get("gap"), run=ft.get("run"), slope5=ft.get("slope"), crosses=ft.get("cross"),
                        source_pv=float(r["hold_pv"]), trigger_pv=float(r["trigger_pv"]),
                        base_buy_basket=";".join(f"{t['security_code']}:{t['amount']}" for t in basket))
            events.append(item)
        arm_events = events[start:]
        delta_contrib = contrib_by_code(next((work / label).glob("*_trades.csv")))
        delta = {c: delta_contrib.get(c, 0) - base_contrib.get(c, 0) for c in set(delta_contrib) | set(base_contrib)}
        top = sorted(delta, key=lambda c: -abs(delta[c]))[:3]
        for c, v in sorted(delta.items(), key=lambda t: -abs(t[1])):
            contributions.append(dict(arm=label, code=c, base=base_contrib.get(c, 0),
                                      candidate=delta_contrib.get(c, 0), delta=v))
        # Order-independent first day on which the executed trade sets differ.
        def daily(rs):
            out = defaultdict(list)
            for t in rs:
                out[t["date"]].append((t["security_code"], t["action"], t["shares"], t["price"], t["reason"]))
            return {d: sorted(v) for d, v in out.items()}
        bday, aday = daily(base), daily(rows)
        first = next((d for d in sorted(set(bday) | set(aday)) if bday.get(d) != aday.get(d)), "")
        for side, day_rows in (("BASE", bday), (label, aday)):
            for c, action, shares, price, reason in day_rows.get(first, []):
                first_changes.append(dict(arm=label, first_date=first, side=side, code=c, action=action,
                                          shares=shares, price=price, reason=reason))
        summaries.append(dict(arm=label, blocked=len(arm_events), distinct_sources=len({e['source'] for e in arm_events}),
                              matched_base=sum(e["base_matched"] for e in arm_events),
                              rebound=sum(e['classification'] == '假摔' for e in arm_events),
                              breakdown=sum(e['classification'] == '走坏' for e in arm_events),
                              censored=sum(e['classification'] == '无后续' for e in arm_events),
                              source_minus_basket60=median(e['source_minus_basket60'] for e in arm_events),
                              first_divergence=first, swap_sales=len(swap_sells(rows)),
                              contrib_delta=sum(delta.values()), top3="/".join(top),
                              top3_signed_fraction=sum(delta[c] for c in top) / sum(delta.values()) if sum(delta.values()) else None))
        def year_returns(label):
            eq = read_ledger(next((work / label).glob("*_equity.csv")))
            nav = {r['date']: float(r['net_equity']) for r in eq}
            last = {}
            for day in sorted(nav):
                last[day[:4]] = nav[day]
            prev = 3_000_000
            out = {}
            for y, value in last.items():
                out[y] = value / prev - 1
                prev = value
            return out
        by, ay = year_returns("BASE"), year_returns(label)
        for y in by:
            annual.append(dict(arm=label, year=y, base=by[y], candidate=ay[y], delta=ay[y] - by[y],
                               partial=y in ("2011", "2026")))
    for name, rs in (("events", events), ("event_summary", summaries), ("contribution", contributions),
                     ("annual", annual), ("first_divergence", first_changes)):
        write_csv(exp / f"{name}_{args.phase}.csv", rs)
    # This is a replay of the three supplied signal events, not a counterfactual live portfolio.
    live = []
    for label, cfg in cases.items():
        if cfg.mode == "off":
            continue
        g = ChopGuard(cfg, mk.raw, mk.ma, bt.load_actions())
        lot = object()
        for s in ("2026-08-19", "2026-08-21", "2026-08-24"):
            i = mk.pos["002714"][s]
            reason = g.blocked("002714", s, i + 1, lot)
            live.append(dict(arm=label, signal_date=s, blocked=bool(reason), **g.features("002714", s)))
            if not reason:
                g.record_sale("002714", s, i + 1, lot, 100)
    write_csv(exp / f"muyuan_signal_replay_{args.phase}.csv", live)
    if args.phase == "r1":
        audit = []
        for r in swap_sells(base):
            c, d = r["security_code"], r["date"]
            i, s = mk.idx(c, d), mk.prev_day(c, d)
            if i is None or i + 20 >= len(mk.days[c]):
                continue
            category, f = classify(mk, c, d)
            audit.append(dict(code=c, date=d, entry_price=mk.raw[c][d],
                              price_20=mk.raw[c][mk.days[c][i + 20]],
                              old_adjusted_return20=mk.adj[c][i + 20] / mk.adj[c][i] - 1,
                              corrected_return20=f[20], corrected_class=category,
                              flat_protected=bool(s and guard.blocked(c, s, 0, None)), amount=r["amount"]))
        write_csv(exp / "forward_return_audit.csv", audit)
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
