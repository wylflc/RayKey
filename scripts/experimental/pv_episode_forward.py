#!/usr/bin/env python3
"""P/V forward returns: daily observations versus first signals in MA60 episodes.

Descriptive only; frozen design: exp_pv_episode_20260914/preregister.md.
No portfolio simulation, production mutation, threshold selection or inference.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv
from panel_tier_forward import load_spans, in_span
from moat_param_lab import month_ends

BUY = 1.0454
GROUPS = ('pv_daily', 'pv_monthly', 'trend_daily', 'trend_ma60_episode',
          'trend_stop_episode', 'trend_ma60_nonoverlap')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def return_indices(days, prices, actions):
    """Self-financing dividend reinvestment; also shares/cash for no reinvestment.

    Events during suspensions are collected at the next quote; rights are funded
    from wealth. The entry-day action cancels in any forward index ratio.
    """
    tri, shares, cash = [], [], []
    value, s, c = 1.0, 1.0, 0.0
    events = sorted(d for d in actions if days[0] < d <= days[-1])
    cursor = 0
    for i, day in enumerate(days):
        factor, distribution = 1.0, 0.0
        while cursor < len(events) and events[cursor] <= day:
            dividend, bonus, rights, subscription = actions[events[cursor]]
            distribution += factor * (dividend - rights * subscription)
            factor *= 1 + bonus + rights
            c += s * (dividend - rights * subscription)
            s *= 1 + bonus + rights
            cursor += 1
        if i:
            value *= (factor * prices[i] + distribution) / prices[i - 1]
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f'Invalid total-return index on {day}')
        tri.append(value)
        shares.append(s)
        cash.append(c)
    return tri, shares, cash


def episodes(eligible, prices, ma60, event_steps, mode='ma60'):
    """First eligible signal stays locked until the specified closing-price break.

    Every quote is visited, including dates without eligibility/PV/panel membership.
    Entry anchor belongs to next-quote execution day and adjusts after that day.
    """
    out, active = [], None
    for i, ok in enumerate(eligible):
        if active is not None:
            if mode == 'stop' and i > active['exec_i']:
                for dividend, bonus, rights, subscription in event_steps[i]:
                    active['anchor'] = ((active['anchor'] - dividend + rights * subscription)
                                        / (1 + bonus + rights))
            line = ma60[i]
            if mode == 'stop' and line is not None and active['anchor'] is not None:
                line = min(line, active['anchor'])
            if line is not None and prices[i] < line:
                active['break_i'] = i
                active = None
        if ok and active is None:
            active = {'signal_i': i, 'exec_i': i + 1, 'break_i': None,
                      'anchor': ma60[i + 1] if i + 1 < len(ma60) else None}
            out.append(active)
    return out


def nonoverlap(events, horizon):
    kept, previous_end = [], -1
    for event in events:
        if event['exec_i'] >= previous_end:
            kept.append(event)
            previous_end = event['exec_i'] + horizon
    return kept


def bucket(pv):
    return '(0,0.6)' if pv < .6 else '[0.6,0.8)' if pv < .8 else '[0.8,1.0454]'


def write_csv(path, rows, fields=None):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--states', type=Path, default=ROOT/'data/processed/a_share_daily_states_adopted.csv')
    ap.add_argument('--panel', type=Path, default=ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv')
    ap.add_argument('--since', default='2011-11-01')
    ap.add_argument('--horizon', type=int, default=250)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.horizon <= 0:
        ap.error('horizon must be positive')
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = [args.states, args.panel, bhv.ACTIONS, Path(__file__),
              ROOT/'scripts/backtest_valuation_strategy.py',
              ROOT/'scripts/experimental/panel_tier_forward.py',
              ROOT/'scripts/experimental/moat_param_lab.py',
              ROOT/'scripts/build_historical_valuation_bands.py',
              args.out/'preregister.md']
    hashes = {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): sha(p) for p in inputs}
    spans = load_spans(args.panel)
    data = defaultdict(dict)
    rows_read = 0
    with args.states.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        header = next(reader)
        c, d, p, v = [header.index(k) for k in ('security_code', 'date', 'close', 'valuation_ratio')]
        for row in reader:
            rows_read += 1
            code, day = row[c].zfill(6), row[d]
            if code not in spans or day < args.since or not row[v] or not in_span(spans[code], day):
                continue
            pv = float(row[v])
            if math.isfinite(pv) and 0 < pv <= BUY:
                if day in data[code]:
                    raise ValueError(f'Duplicate state: {code} {day}')
                data[code][day] = (pv, float(row[p]))
    print(f'Streamed {rows_read:,} states; cheap in-panel rows {sum(map(len,data.values())):,}; codes {len(data)}', flush=True)
    actions = bt.load_actions()
    samples, counts = defaultdict(list), defaultdict(int)
    details, coverage = [], []
    mismatches, max_mismatch = 0, 0.0
    for code in sorted(data):
        raw = bhv.load_ohlcv(code)
        if not raw:
            coverage.append({'code': code, 'first_quote': '', 'last_quote': '', 'cheap_states': len(data[code]), 'missing_state_quotes': len(data[code]), 'rights_events': 0})
            continue
        price_path = bhv.OHLCV_DIR/f'{code}.csv'
        hashes[str(price_path.relative_to(ROOT))] = sha(price_path)
        days, prices = [r[0] for r in raw], [r[1] for r in raw]
        ad = actions.get(code, {})
        ma = bt.adjusted_moving_averages(dict(raw), ad, windows=(20, 60))
        m60 = [ma.get(d, {}).get(60) for d in days]
        tri, shares, cash = return_indices(days, prices, ad)
        steps, cursor = [[] for _ in days], 0
        event_days = sorted(ad)
        for i, day in enumerate(days):
            while cursor < len(event_days) and event_days[cursor] <= day:
                steps[i].append(ad[event_days[cursor]])
                cursor += 1
        eligible, cheap = [], []
        monthend = set(month_ends(days))
        for i, day in enumerate(days):
            state = data[code].get(day)
            cheap.append(state is not None)
            if state:
                delta = abs(prices[i] - state[1])
                max_mismatch = max(max_mismatch, delta)
                mismatches += delta > .00051
            m = ma.get(day, {})
            eligible.append(bool(state and 20 in m and 60 in m and prices[i] > m[20] > m[60]))
        if mismatches:
            raise ValueError(f'State/price mismatch count {mismatches}, max {max_mismatch}')
        ep = episodes(eligible, prices, m60, steps)
        sp = episodes(eligible, prices, m60, steps, 'stop')
        picks = {
            'pv_daily': [{'signal_i': i} for i, ok in enumerate(cheap) if ok],
            'pv_monthly': [{'signal_i': i} for i, ok in enumerate(cheap) if ok and days[i] in monthend],
            'trend_daily': [{'signal_i': i} for i, ok in enumerate(eligible) if ok],
            'trend_ma60_episode': ep, 'trend_stop_episode': sp,
            'trend_ma60_nonoverlap': nonoverlap(ep, args.horizon)}
        coverage.append({'code': code, 'first_quote': days[0], 'last_quote': days[-1], 'cheap_states': len(data[code]),
                         'missing_state_quotes': len(set(data[code])-set(days)),
                         'rights_events': sum(bool(a[2]) for d,a in ad.items() if days[0] < d <= days[-1])})
        for group, events in picks.items():
            for event in events:
                i = event['signal_i']
                start, end = i + 1, i + 1 + args.horizon
                pv = data[code][days[i]][0]
                b = bucket(pv)
                ret = tri[end]/tri[start]-1 if end < len(days) else None
                cashret = ((shares[end]*prices[end]+cash[end]-cash[start])/shares[start]/prices[start]-1
                           if end < len(days) else None)
                for band in (b, 'all_cheap'):
                    key = group, band
                    counts[key] += 1
                    if ret is not None:
                        samples[key].append((code, days[i][:4], ret, cashret))
                if 'episode' in group or 'nonoverlap' in group:
                    brk = event.get('break_i')
                    details.append({'group': group, 'code': code, 'signal_date': days[i], 'pv': pv,
                                    'bucket': b, 'execution_date': days[start] if start < len(days) else '',
                                    'end_date': days[end] if end < len(days) else '',
                                    'break_date': days[brk] if brk is not None else '',
                                    'return_250d': ret, 'cash_return_250d': cashret,
                                    'complete': ret is not None, 'price_end': days[-1]})
    summary, by_code, annual = [], [], []
    for key in sorted(counts):
        group, band = key
        obs = samples[key]
        vals = [r[2] for r in obs]
        codes, years = defaultdict(list), defaultdict(list)
        for c, y, v, cashret in obs:
            codes[c].append(v)
            years[y].append(v)
        summary.append({'group': group, 'bucket': band, 'signals': counts[key], 'complete': len(vals),
                        'missing_forward': counts[key]-len(vals), 'codes': len(codes),
                        'median': st.median(vals) if vals else None, 'mean': st.mean(vals) if vals else None,
                        'positive_fraction': st.mean(v > 0 for v in vals) if vals else None,
                        'median_of_code_medians': st.median([st.median(v) for v in codes.values()]) if vals else None,
                        'cash_median': st.median([r[3] for r in obs]) if vals else None,
                        'max_code_sample_fraction': max(map(len,codes.values()))/len(vals) if vals else None})
        by_code += [{'group': group, 'bucket': band, 'code': c, 'n': len(v), 'median': st.median(v)} for c,v in sorted(codes.items())]
        annual += [{'group': group, 'bucket': band, 'signal_year': y, 'n': len(v), 'median': st.median(v)} for y,v in sorted(years.items())]
    write_csv(args.out/'summary.csv', summary)
    write_csv(args.out/'episodes.csv', details)
    write_csv(args.out/'by_code.csv', by_code)
    write_csv(args.out/'annual.csv', annual)
    write_csv(args.out/'coverage.csv', coverage)
    manifest = {'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'job_id': os.getenv('SLURM_JOB_ID'),
                'since': args.since, 'horizon_stock_trading_days': args.horizon, 'buy_line': BUY,
                'states_streamed': rows_read, 'state_close_mismatches': mismatches,
                'max_state_close_difference': max_mismatch, 'input_sha256': hashes,
                'results': summary, 'output_sha256': {p.name: sha(p) for p in args.out.glob('*.csv')}}
    (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    for r in summary:
        if r['bucket'] == 'all_cheap':
            print(json.dumps(r, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
