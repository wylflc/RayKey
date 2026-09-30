"""读 runs/：①长跑锚点 09-29 持仓；②亏损持仓的退出路径与时长（S15 对照 OLD）。

    python3 analyze.py            # → holdings.json、exits.json、exits_cases.csv
"""
import collections
import csv
import gzip
import json
import statistics
from datetime import date

from common import EXP, OHLCV, PANEL_STATES, UNTIL, securities
import backtest_valuation_strategy as bt
import sweep_backtest_configs as sw

bt.OHLCV_DIR = OHLCV
RUNS = EXP / 'runs'
ANCHORS = ('2009-11-01', '2011-11-01')
NAMES = {c: n for c, (n, _) in securities().items()}
DEEP = -0.20


def read(path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def route(reason: str) -> str:
    if '移出股票库' in reason:
        return '出名单'
    if '股债' in reason:
        return '股债总仓位上限'
    if '换仓' in reason or '让位' in reason:
        return '换仓·盈利偏离' if '盈利偏离' in reason else '换仓·涨幅减持源' if '涨幅≥' in reason else '换仓·弱势源'
    if reason.startswith('涨幅≥'):
        return '涨幅减持'
    if '止损' in reason or '跌破' in reason:
        return '止损'
    if '强制平仓' in reason:
        return '强平'
    if '退市' in reason:
        return '退市'
    if '回测截止' in reason:
        return '仍持有'
    return reason


def years(a: str, b: str) -> float:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days / 365.25


def load(arm, start):
    d = RUNS / f'{arm}_{start}'
    with gzip.open(d / 'holdings_daily.csv.gz', 'rt', newline='') as f:
        daily = list(csv.DictReader(f))
    return dict(final=json.loads((d / 'final.json').read_text()), cycles=read(d / 'cycles.csv'),
                ledger=read(d / 'ledger.csv'), daily=daily, equity=read(d / 'equity.csv'))


def states_on(day: str, codes: set[str]) -> dict:
    out = {}
    for side, name in (('pv', 'a_share_daily_states_adopted.csv'), ('hold_pv', 'a_share_daily_states_hold.csv')):
        with (PANEL_STATES / name).open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                if r['security_code'] in codes and r['date'] <= day:
                    out.setdefault(r['security_code'], {})[side] = (r['date'], float(r['valuation_ratio']),
                                                                   float(r['intrinsic_value']))
    return out


def segments(run, prices):
    """逐票连续持有段：入场、出场（未出场为空）、逐日盈亏与权重、段内卖出理由。"""
    days = sorted({r['date'] for r in run['equity']})
    held = collections.defaultdict(dict)
    for r in run['daily']:
        held[r['code']][r['date']] = r
    sells = collections.defaultdict(list)
    for r in run['ledger']:
        if r['action'] == '卖出':
            sells[r['security_code']].append(r)
    lots = {(c['code'], c['entry_date']): c for c in run['cycles']}
    out = []
    for code, rows in held.items():
        seq = sorted(rows)
        start = prev = None
        idx = {d: i for i, d in enumerate(days)}
        chunks = []
        for d in seq:
            if start is None:
                start = d
            elif idx[d] != idx[prev] + 1:
                chunks.append((start, prev))
                start = d
            prev = d
        chunks.append((start, prev))
        for a, b in chunks:
            exit_day = days[idx[b] + 1] if idx[b] + 1 < len(days) else None
            path = []
            for d in days[idx[a]:idx[b] + 1]:
                r, px = rows[d], prices.get(code, {}).get(d)
                if px:
                    path.append((d, px / float(r['cost']) - 1, float(r['shares']) * px / float(r['equity'])))
            lo = min(path, key=lambda x: x[1]) if path else (a, 0., 0.)
            after = [p for p in path if p[0] >= lo[0]]
            sold = [s for s in sells[code] if a <= s['date'] <= (exit_day or UNTIL)]
            final = [s for s in sold if s['date'] == exit_day]
            lot = lots.get((code, a))
            out.append(dict(
                code=code, name=NAMES.get(code, ''), entry=a, exit=exit_day or '',
                years=round(years(a, exit_day or UNTIL), 2), min_pnl=round(lo[1], 4), min_date=lo[0],
                max_weight=round(max((p[2] for p in path), default=0.), 4),
                weight_at_min=round(lo[2], 4), underwater_share=round(sum(p[1] < 0 for p in path) / max(1, len(path)), 3),
                recovered=bool(after) and max(p[1] for p in after) >= 0, reached_30=bool(after) and max(p[1] for p in after) >= 0.30,
                last_pnl=round(path[-1][1], 4) if path else None,
                exit_route=route(final[-1]['reason']) if final else ('仍持有' if exit_day is None else '?'),
                sell_routes=dict(collections.Counter(route(s['reason']) for s in sold)),
                cycle_return=round(float(lot['proceeds']) / float(lot['invested']) - 1, 4) if lot and float(lot['invested']) else None,
                buys=int(lot['buys']) if lot else None))
    return out


def holdings(arm, start, run, prices, pv):
    fin = run['final']
    eq = fin['equity']
    rows = []
    for code, h in fin['holdings'].items():
        px = prices[code][max(d for d in prices[code] if d <= UNTIL)]
        mv = h['shares'] * px
        rows.append(dict(code=code, name=NAMES.get(code, ''), shares=h['shares'], close=px, weight=round(mv / eq, 4),
                         cost=round(h['cost'], 4), pnl=round(px / h['cost'] - 1, 4),
                         pv=pv.get(code, {}).get('pv'), hold_pv=pv.get(code, {}).get('hold_pv')))
    rows.sort(key=lambda r: -r['weight'])
    mv = sum(r['weight'] for r in rows) * eq
    return dict(arm=arm, start=start, date=fin['date'], equity=round(eq), debt=round(fin['debt']),
                gross_over_nav=round(mv / eq, 4), multiple=round(eq / 3e6, 2),
                cagr=round((eq / 3e6) ** (1 / years(start, UNTIL)) - 1, 4), rows=rows)


def main():
    runs = {(a, s): load(a, s) for a in ('S15', 'OLD') for s in sw.DEFAULT_STARTS}
    codes = set()
    for r in runs.values():
        codes |= {x['code'] for x in r['daily']}
    prices = bt.load_prices(codes)
    final_codes = set().union(*[set(r['final']['holdings']) for r in runs.values()])
    pv = states_on(UNTIL, final_codes)
    out = dict(anchors=[], across_starts={}, september={})
    for (arm, start), run in runs.items():
        if start in ANCHORS:
            out['anchors'].append(holdings(arm, start, run, prices, pv))
            out['september'][f'{arm}_{start}'] = [dict(date=r['date'], code=r['security_code'], name=NAMES.get(r['security_code'], ''),
                                                       action=r['action'], shares=r['shares'], price=r['price'], reason=r['reason'])
                                                  for r in run['ledger'] if r['date'] > '2026-08-28']
    for arm in ('S15', 'OLD'):
        agg = collections.defaultdict(list)
        for s in sw.DEFAULT_STARTS:
            h = holdings(arm, s, runs[(arm, s)], prices, pv)
            for r in h['rows']:
                agg[r['code']].append(r['weight'])
        out['across_starts'][arm] = sorted(([c, NAMES.get(c, ''), len(w), round(statistics.median(w), 4)] for c, w in agg.items()),
                                           key=lambda x: (-x[2], -x[3]))
    (EXP / 'holdings.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')

    segs = {k: segments(r, prices) for k, r in runs.items()}
    exits = dict(deep=DEEP, per_arm={}, cases={})
    with (EXP / 'exits_cases.csv').open('w', newline='', encoding='utf-8') as f:
        fields = ['arm', 'start', *segs[('S15', ANCHORS[0])][0].keys()]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for (arm, start), rows in segs.items():
            for r in rows:
                w.writerow(dict(arm=arm, start=start, **r))
    for arm in ('S15', 'OLD'):
        # 跨起点同一事件（同票同出场日）只计一次
        uniq = {}
        for s in sw.DEFAULT_STARTS:
            for r in segs[(arm, s)]:
                uniq.setdefault((r['code'], r['exit'] or 'open'), r)
        allc = list(uniq.values())
        deep = [r for r in allc if r['min_pnl'] <= DEEP]
        closed = [r for r in deep if r['exit']]
        routes = collections.Counter(r['exit_route'] for r in deep)
        exits['per_arm'][arm] = dict(
            cycles=len(allc), deep=len(deep), routes=dict(routes.most_common()),
            deep_open=[dict(code=r['code'], name=r['name'], entry=r['entry'], min_pnl=r['min_pnl'], last_pnl=r['last_pnl'],
                            max_weight=r['max_weight']) for r in deep if not r['exit']],
            years_to_exit=dict(median=statistics.median([r['years'] for r in closed]) if closed else None,
                               p25=statistics.quantiles([r['years'] for r in closed], n=4)[0] if len(closed) > 3 else None,
                               p75=statistics.quantiles([r['years'] for r in closed], n=4)[2] if len(closed) > 3 else None),
            years_min_to_exit=statistics.median([years(r['min_date'], r['exit']) for r in closed]) if closed else None,
            recovered_share=round(sum(r['recovered'] for r in deep) / len(deep), 3) if deep else None,
            by_route={k: dict(n=len(v), median_years=statistics.median([r['years'] for r in v]),
                              median_return=statistics.median([r['cycle_return'] for r in v if r['cycle_return'] is not None] or [0]),
                              median_min=statistics.median([r['min_pnl'] for r in v]))
                      for k, v in ((k, [r for r in deep if r['exit_route'] == k]) for k in routes)})
        exits['cases'][arm] = {s: [r for r in segs[(arm, s)] if r['code'] in ('600585', '600970')] for s in sw.DEFAULT_STARTS}
    (EXP / 'exits.json').write_text(json.dumps(exits, ensure_ascii=False, indent=1) + '\n')
    for h in out['anchors']:
        print(h['arm'], h['start'], h['equity'], h['gross_over_nav'], [(r['name'], r['weight'], r['pnl']) for r in h['rows'][:6]])
    for arm, e in exits['per_arm'].items():
        print(arm, {k: v for k, v in e.items() if k not in ('by_route', 'deep_open')})


if __name__ == '__main__':
    main()
