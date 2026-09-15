#!/usr/bin/env python3
"""Historical top three under strict or stop-latched signal eligibility.

Signal description only. Design and data limitations are recorded beside outputs.
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import json
import math
import os
import shlex
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(Path(__file__).resolve().parent)]
import backtest_valuation_strategy as bt
import build_historical_valuation_bands as bhv
from panel_tier_forward import load_spans, in_span
from pv_episode_forward import return_indices, sha
from sweep_backtest_configs import BASE


def anniversary(day, years):
    d = date.fromisoformat(day)
    year = d.year + years
    return date(year, d.month, min(d.day, calendar.monthrange(year, d.month)[1])).isoformat()


def on_or_after(days, day):
    i = bisect.bisect_left(days, day)
    return days[i] if i < len(days) else ''


def forward(row, years, market_days, prices, tri):
    """T+1 market close to anniversary market close; never postpone a suspension."""
    start = row['execution_date']
    target = anniversary(start, years) if start else ''
    end = on_or_after(market_days, target) if target else ''
    reason = ('execution_after_cutoff' if not start else
              'execution_quote_missing' if start not in prices else
              'forward_incomplete' if not end else
              'endpoint_after_stock_history' if end > max(prices) else
              'endpoint_quote_missing' if end not in prices else 'complete')
    return {f'target_{years}y': target, f'end_{years}y': end,
            f'status_{years}y': reason,
            f'end_close_{years}y': prices.get(end, ''),
            f'return_{years}y': tri[end] / tri[start] - 1 if reason == 'complete' else ''}


def nonoverlap_calendar(rows, years):
    kept, previous_end = [], ''
    for row in rows:
        start = row['execution_date']
        if start and start >= previous_end:
            kept.append(row)
            # Reserve the planned horizon even when its endpoint quote is missing.
            previous_end = row[f'end_{years}y'] or row[f'target_{years}y']
    return kept


def write_csv(path, rows, fields=None):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(group, years, rows):
    good = [r for r in rows if r[f'status_{years}y'] == 'complete']
    values = [r[f'return_{years}y'] for r in good]
    counts = Counter(r['security_code'] for r in good)
    return {'group': group, 'years': years, 'signals': len(rows), 'complete': len(good),
            'missing': len(rows) - len(good),
            'signal_companies': len({r['security_code'] for r in rows}),
            'complete_companies': len(counts),
            'median_return': st.median(values) if values else '',
            'mean_return': st.mean(values) if values else '',
            'positive_fraction': st.mean(v > 0 for v in values) if values else '',
            'max_company_fraction': max(counts.values()) / len(good) if good else ''}


def period_key(day, frequency):
    return day[:4] if frequency == 'annual' else f'{day[:4]}Q{(int(day[5:7])-1)//3+1}'


def snapshots(market_days, byday, frequency):
    seen, result = set(), []
    for day in market_days:
        period = period_key(day, frequency)
        if period in seen:
            continue
        seen.add(period)
        # Empty and short lists are retained; do not search later for a full top 3.
        for rank in range(1, 4):
            picks = byday.get(day, [])
            result.append({'period': period, **picks[rank-1]} if len(picks) >= rank else
                          {'period': period, 'signal_date': day, 'rank': rank,
                           'security_code': '', 'security_name': '无合格标的',
                           'eligible_count': picks[0]['eligible_count'] if picks else 0})
    return result


def membership_segments(market_days, byday):
    segments, previous = [], None
    for day in market_days:
        picks = byday.get(day, [])
        members = tuple(sorted(r['security_code'] for r in picks))
        if members != previous:
            segments.append({'segment_id':len(segments)+1, 'segment_start':day,
                             'segment_end':day, 'trading_days':1, 'picks':picks})
            previous = members
        else:
            segments[-1]['segment_end'] = day
            segments[-1]['trading_days'] += 1
    rows = []
    for segment in segments:
        picks = segment['picks']
        meta = {k:v for k,v in segment.items() if k != 'picks'}
        for rank in range(1,4):
            rows.append({**meta, **picks[rank-1]} if len(picks) >= rank else
                        {**meta, 'signal_date':segment['segment_start'], 'rank':rank,
                         'security_code':'', 'security_name':'无合格标的',
                         'eligible_count':picks[0]['eligible_count'] if picks else 0})
    return rows


def stop_latched_eligibility(days, prices, ma, cheap_days, actions):
    """Activate on a full signal; only a closing stop breach clears memory.

    Virtual entry anchors at the next quote's MA60, without using that future MA
    on the signal day. A suspension can delay this research anchor, never the
    independently measured T+1 execution/return date. No position is simulated.
    """
    eligible, cycles, active = {}, [], None
    event_days = sorted(actions)
    cursor = 0
    for day in days:
        steps = []
        while cursor < len(event_days) and event_days[cursor] <= day:
            steps.append(actions[event_days[cursor]])
            cursor += 1
        m = ma.get(day, {})
        m20, m60 = m.get(20), m.get(60)
        if active is not None:
            if active['anchor_date']:
                for dividend, bonus, rights, subscription in steps:
                    active['last_adjusted_anchor'] = ((active['last_adjusted_anchor'] - dividend
                                                      + rights * subscription) / (1 + bonus + rights))
            elif m60 is not None:
                active['anchor_date'] = day
                active['original_anchor'] = active['last_adjusted_anchor'] = m60
            if m60 is not None and active['anchor_date']:
                stop = min(active['last_adjusted_anchor'], m60)
                if prices[day] < stop:
                    active.update(reset_date=day, reset_close=prices[day], reset_stop_line=stop)
                    active = None
        full = day in cheap_days and m20 is not None and m60 is not None and prices[day] > m20 > m60
        if active is None and full:
            active = {'activation_date':day, 'activation_close':prices[day], 'activation_ma20':m20,
                      'activation_ma60':m60, 'anchor_date':'', 'original_anchor':'',
                      'last_adjusted_anchor':'', 'reset_date':'', 'reset_close':'', 'reset_stop_line':''}
            cycles.append(active)
        if active is not None and day in cheap_days and m20 is not None and m60 is not None and m20 > m60:
            anchor = active['last_adjusted_anchor']
            eligible[day] = {'activation_date':active['activation_date'], 'anchor_date':active['anchor_date'],
                             'stop_anchor':anchor, 'stop_line':min(anchor,m60) if anchor != '' else '',
                             'qualification':'initial' if active['activation_date']==day else
                                             'continued' if prices[day]>m20 else 'continued_below_ma20'}
    return eligible, cycles


def ma60_counting_episodes(eligible, prices, ma60):
    """MA60 counting only: signals already below MA60 end on that same quote.

    Latched eligibility can be below MA60 without breaching its fixed anchor.
    Such an observation is retained as a zero-length counting episode, not
    carried into the following above-MA60 regime or called a new activation.
    """
    result, active = [], None
    for i, ok in enumerate(eligible):
        below = ma60[i] is not None and prices[i] < ma60[i]
        if active is not None and below:
            active['break_i'] = i
            active = None
        if ok and active is None:
            event = {'signal_i':i,'exec_i':i+1,'break_i':i if below else None}
            result.append(event)
            if not below:
                active = event
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--since', default='2009-11-01')
    ap.add_argument('--eligibility', choices=('strict','stop-latched'), default='strict')
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    flags = shlex.split(BASE)
    states = ROOT / flags[flags.index('--daily-states')+1]
    panel = ROOT / flags[flags.index('--universe-file')+1]
    buy = 1 - float(flags[flags.index('--width')+1])
    market_raw = bhv.load_ohlcv('INDEX_000300')
    market_days = [d for d, p in market_raw]
    cutoff = market_days[-1]
    market_set = set(market_days)
    market_index = {d: i for i, d in enumerate(market_days)}
    signal_days = [d for d in market_days if d >= args.since]
    spans = load_spans(panel)
    names = {}
    with panel.open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            names[r['security_code'].zfill(6)] = r['security_name']
    inputs = [states, panel, bhv.ACTIONS, bhv.OHLCV_DIR/'INDEX_000300.csv',
              Path(__file__), Path(__file__).with_name('pv_episode_forward.py'),
              Path(__file__).with_name('panel_tier_forward.py'),
              ROOT/'scripts/sweep_backtest_configs.py', ROOT/'scripts/backtest_valuation_strategy.py',
              ROOT/'scripts/build_historical_valuation_bands.py', args.out/'preregister.md']
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    cheap = defaultdict(dict)
    state_min, state_max, read_count, evening_rows = '9999', '', 0, 0
    with states.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        header = next(reader)
        ci, di, pi, vi, ii, ai = [header.index(k) for k in
                                  ('security_code', 'date', 'close', 'valuation_ratio',
                                   'intrinsic_value', 'band_available_at')]
        for r in reader:
            read_count += 1
            code, day = r[ci].zfill(6), r[di]
            state_min, state_max = min(state_min, day), max(state_max, day)
            if code not in spans or not args.since <= day <= cutoff or not r[vi]:
                continue
            pv = float(r[vi])
            if not math.isfinite(pv) or not 0 < pv <= buy or not in_span(spans[code], day):
                continue
            if day in cheap[code]:
                raise ValueError(f'Duplicate state {code} {day}')
            if day not in market_set:
                raise ValueError(f'Calendar mismatch {code} {day}')
            # Workflow 6.5: evening reports take effect on the preceding market
            # session, while band_available_at retains the original notice date.
            if r[ai] > day:
                if bisect.bisect_left(market_days, r[ai])-1 != market_index[day]:
                    raise ValueError(f'State-effective mismatch {code} {day}')
                evening_rows += 1
            cheap[code][day] = (pv, float(r[pi]), float(r[ii]), r[ai])
    print(f'Streamed {read_count:,} states; {len(cheap)} cheap companies; cutoff {cutoff}', flush=True)
    actions = bt.load_actions()
    qualified, strict_qualified = defaultdict(list), defaultdict(list)
    activation_cycles = []
    coverage = []
    for code, states_for_code in sorted(cheap.items()):
        raw = bhv.load_ohlcv(code)
        if not raw:
            raise ValueError(f'Missing price file {code}')
        hashes[str((bhv.OHLCV_DIR/f'{code}.csv').relative_to(ROOT))] = sha(bhv.OHLCV_DIR/f'{code}.csv')
        prices = dict(raw)
        if len(prices) != len(raw):
            raise ValueError(f'Duplicate price date {code}')
        ma = bt.adjusted_moving_averages(prices, actions.get(code, {}), windows=(20,60))
        coverage.append({'security_code': code, 'security_name': names[code],
                         'first_quote': raw[0][0], 'last_quote': raw[-1][0],
                         'cheap_states': len(states_for_code)})
        if args.eligibility == 'stop-latched':
            latched, cycles = stop_latched_eligibility([d for d in prices if d <= cutoff], prices, ma,
                                                      states_for_code, actions.get(code, {}))
            activation_cycles.extend({'security_code':code,'security_name':names[code],**r} for r in cycles)
        for day, (pv, close, value, available) in states_for_code.items():
            if day not in prices or abs(prices[day]-close) > .00051:
                raise ValueError(f'State/price mismatch {code} {day}')
            m = ma.get(day, {})
            full = 20 in m and 60 in m and close > m[20] > m[60]
            if full:
                strict_qualified[day].append({'security_code':code,'pv':pv})
            eligible_now = full if args.eligibility == 'strict' else day in latched
            if eligible_now:
                row = {'signal_date': day, 'security_code': code,
                       'security_name': names[code], 'pv': pv,
                       'signal_close': close, 'intrinsic_value': value,
                       'ma20': m[20], 'ma60': m[60], 'band_available_at': available}
                if args.eligibility == 'stop-latched':
                    row.update(latched[day])
                qualified[day].append(row)
    bycode = defaultdict(list)
    daily = []
    for day in signal_days:
        rows = sorted(qualified.get(day, []), key=lambda r: (r['pv'], r['security_code']))
        for rank, r in enumerate(rows[:3], 1):
            i = market_index[day]+1
            r.update(rank=rank, eligible_count=len(rows),
                     execution_date=market_days[i] if i < len(market_days) else '')
            daily.append(r)
            bycode[r['security_code']].append(r)
    if not daily:
        raise ValueError('No eligible signals')
    cycle_rows, nonoverlap_rows = [], {1: [], 3: []}
    for code, rows in sorted(bycode.items()):
        raw = [(d,p) for d,p in bhv.load_ohlcv(code) if d <= cutoff]
        days, prices = [d for d,p in raw], dict(raw)
        tri_values, _, _ = return_indices(days, list(prices.values()), actions.get(code, {}))
        tri = dict(zip(days,tri_values))
        ma = bt.adjusted_moving_averages(prices, actions.get(code, {}), windows=(60,))
        row_map = {r['signal_date']: r for r in rows}
        for r in rows:
            r['execution_close'] = prices.get(r['execution_date'], '')
            r['price_history_end'] = days[-1]
            for h in (1,3):
                r.update(forward(r, h, market_days, prices, tri))
        events = ma60_counting_episodes([d in row_map for d in days], list(prices.values()),
                                       [ma.get(d,{}).get(60) for d in days])
        company_cycles = []
        for event in events:
            r = dict(row_map[days[event['signal_i']]])
            br = event['break_i']
            r['ma60_break_date'] = days[br] if br is not None else ''
            company_cycles.append(r)
        cycle_rows.extend(company_cycles)
        for h in (1,3):
            nonoverlap_rows[h].extend(nonoverlap_calendar(company_cycles, h))
    byday = defaultdict(list)
    for r in daily:
        byday[r['signal_date']].append(r)
    quarterly = snapshots(signal_days, byday, 'quarterly')
    annual = snapshots(signal_days, byday, 'annual')
    segments = membership_segments(signal_days, byday)
    fields = list(daily[0])
    write_csv(args.out/'daily_top3.csv', daily)
    write_csv(args.out/'segments_top3.csv', segments,
              ['segment_id','segment_start','segment_end','trading_days']+fields)
    if args.eligibility == 'stop-latched':
        write_csv(args.out/'activation_cycles.csv', activation_cycles)
    write_csv(args.out/'quarterly_top3.csv', quarterly, ['period']+fields)
    write_csv(args.out/'annual_top3.csv', annual, ['period']+fields)
    write_csv(args.out/'ma60_episodes.csv', sorted(cycle_rows,key=lambda r:(r['signal_date'],r['rank'])))
    groups = {'daily_top3': daily, 'segment_starts': [r for r in segments if r['security_code']],
              'quarterly_top3': [r for r in quarterly if r['security_code']],
              'annual_top3': [r for r in annual if r['security_code']], 'ma60_episodes': cycle_rows}
    if args.eligibility == 'stop-latched':
        # First top-3 appearance per activation, retaining the original stop
        # anchor even when a stock enters the top three long after activation.
        seen, stop_rows = set(), []
        for r in daily:
            key = r['security_code'], r['activation_date']
            if key not in seen:
                seen.add(key)
                stop_rows.append(r)
        groups['activation_first_top3'] = stop_rows
        write_csv(args.out/'activation_first_top3.csv', stop_rows)
    for h in (1,3):
        write_csv(args.out/f'ma60_nonoverlap_{h}y.csv', sorted(nonoverlap_rows[h],key=lambda r:(r['signal_date'],r['rank'])))
    summary, yearly, company = [], [], []
    for h in (1,3):
        for group, rows in {**groups, 'ma60_nonoverlap': nonoverlap_rows[h]}.items():
            summary.append(summarize(group,h,rows))
            for year in sorted({r['signal_date'][:4] for r in rows}):
                yearly.append({'signal_year':year, **summarize(group,h,[r for r in rows if r['signal_date'][:4]==year])})
            for code in sorted({r['security_code'] for r in rows}):
                company.append({'security_code':code, 'security_name':names[code],
                                **summarize(group,h,[r for r in rows if r['security_code']==code])})
    write_csv(args.out/'summary.csv', summary)
    write_csv(args.out/'by_year.csv', yearly)
    write_csv(args.out/'by_company.csv', company)
    write_csv(args.out/'coverage.csv', coverage)
    counts = [{'signal_date':d, 'eligible_count':len(qualified.get(d, [])),
               'top3_count':min(3,len(qualified.get(d, [])))} for d in signal_days]
    write_csv(args.out/'daily_coverage.csv', counts)
    manifest = {'completed_at_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                'job_id':os.getenv('SLURM_JOB_ID'), 'since':args.since, 'cutoff':cutoff,
                'eligibility':args.eligibility,
                'buy_line':buy, 'base_flags':BASE, 'states_rows_read':read_count,
                'states_date_range':[state_min,state_max], 'market_days':len(signal_days),
                'cheap_rows_using_prev_trading_day_disclosure':evening_rows,
                'days_with_signals':len(byday), 'days_without_signals':sum(r['top3_count']==0 for r in counts),
                'membership_segments':len(segments)//3,
                'days_with_fewer_than_three':sum(r['top3_count']<3 for r in counts),
                'all_eligible_observations':sum(map(len, qualified.values())),
                'rank_tie_break':'valuation_ratio rounded in states, then security_code ascending',
                'return_basis':'calendar 1/3 years from next market-day close; gross total return with dividend reinvestment and self-financed rights',
                'missing_reasons':{str(h):dict(Counter(r[f'status_{h}y'] for r in daily)) for h in (1,3)},
                'input_sha256':hashes, 'results':summary}
    if args.eligibility == 'stop-latched':
        strict_byday = {d:[{**r,'rank':i,'eligible_count':len(rs)} for i,r in
                          enumerate(sorted(rs,key=lambda r:(r['pv'],r['security_code']))[:3],1)]
                        for d,rs in strict_qualified.items()}
        old = membership_segments(signal_days, strict_byday)
        old_days = [int(r['trading_days']) for r in old if r['rank']==1]
        new_days = [int(r['trading_days']) for r in segments if r['rank']==1]
        comparison = {'strict_segments':len(old)//3,'latched_segments':len(segments)//3,
                      'strict_average_days':st.mean(old_days),'latched_average_days':st.mean(new_days),
                      'strict_median_days':st.median(old_days),'latched_median_days':st.median(new_days),
                      'strict_one_day_segments':old_days.count(1),'latched_one_day_segments':new_days.count(1),
                      'changed_membership_days':sum({r['security_code'] for r in strict_byday.get(d,[])} !=
                                                     {r['security_code'] for r in byday.get(d,[])} for d in signal_days),
                      'below_ma20_top3_rows':sum(r['qualification']=='continued_below_ma20' for r in daily),
                      'activations':len(activation_cycles),
                      'stop_resets':sum(bool(r['reset_date']) for r in activation_cycles)}
        manifest['eligibility_comparison'] = comparison
        write_csv(args.out/'eligibility_comparison.csv',[comparison])
    manifest['output_sha256']={p.name:sha(p) for p in sorted(args.out.glob('*.csv'))}
    (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('input_sha256','output_sha256','base_flags')},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
