"""OI-224 第二批读数（preregister.md 1～6）：各臂对 BASE 的读数标记、执行读数、第 13 款策略层、陷阱读数与第 11 款案例归因。

    python3 readings.py     # → readings.json、readings.md、report_<臂>.txt、case_<臂>.md
"""
import bisect
import contextlib
import csv
import glob
import json
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
import sweep_backtest_configs as sw  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from run import ACTIONS, ARMS, STATES  # noqa: E402

LINE = 1.0495                               # v4.215 买入线
TRAP_CASES = ('T11', 'T01', 'T02')          # 宇通 2015–18、海螺 2019–21、神华 2012–13（具名陷阱，preregister 第 3 条）


def shift(day, months):
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    import calendar
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), calendar.monthrange(y, m)[1]):02d}'


def trades_of(arm):
    out = {}
    for path in sorted(glob.glob(str(EXP / 'trades' / f'{arm}full*_trades.csv'))):
        start = Path(path).name[len(arm) + 4:len(arm) + 12]
        with open(path, newline='', encoding='utf-8') as f:
            out[f'{start[:4]}-{start[4:6]}-{start[6:]}'] = list(csv.DictReader(f))
    assert len(out) == len(sw.DEFAULT_STARTS), (arm, len(out))
    return out


def execution(rows, eps, pv, arms_trades, series):
    """`execution_gap.py` 同口径：估值已识别的机会段 × 早于机会期的起点。"""
    recognized = []
    for ep in eps:
        if ep[0]['label'] != audit.OPP:
            continue
        zone = [r for r in ep if (v := pv.get((r['code'], r['date']))) is not None and v <= LINE]
        if zone:
            recognized.append(dict(code=ep[0]['code'], start=zone[0]['date'], end=shift(ep[-1]['date'], 36)))
    out = {}
    for arm, starts in arms_trades.items():
        pairs = []
        for e in recognized:
            if e['code'] not in series:
                continue
            days, tr = series[e['code']]
            at = lambda d: tr[days[bisect.bisect_right(days, d) - 1]]
            span = (date.fromisoformat(min(e['end'], days[-1])) - date.fromisoformat(e['start'])).days
            for start, cycles in starts.items():
                if start > e['start']:
                    continue
                cs = [c for c in cycles if c['security_code'].zfill(6) == e['code'] and c['entry_date'] <= e['end'] and c['exit_date'] >= e['start']]
                held = sum((date.fromisoformat(min(c['exit_date'], e['end'])) - date.fromisoformat(max(c['entry_date'], e['start']))).days for c in cs)
                stops = [c for c in cs if '止损' in c['exit_reason']]
                reb = [at(shift(c['exit_date'], 6)) / at(c['exit_date']) - 1 for c in stops if shift(c['exit_date'], 6) <= days[-1]]
                already = any(c['entry_date'] < e['start'] for c in cs)
                first = min((c['entry_date'] for c in cs if c['entry_date'] >= e['start']), default=None)
                prem = delay = None
                if first and not already:
                    lo = min(tr[d] for d in days[bisect.bisect_left(days, e['start']):bisect.bisect_right(days, first)])
                    prem, delay = at(first) / lo - 1, (date.fromisoformat(first) - date.fromisoformat(e['start'])).days
                pairs.append(dict(held=bool(cs), cycles=len(cs), stops=len(stops), reb=reb, prem=prem, delay=delay,
                                  in_market=held / span if span > 0 else None))
        med = lambda xs: statistics.median(xs) if xs else None
        h = [p for p in pairs if p['held']]
        firsts = [p for p in h if p['prem'] is not None]
        rb = [x for p in h for x in p['reb']]
        out[arm] = dict(pairs=len(pairs), never_held=1 - len(h) / len(pairs), churn_3plus=sum(p['cycles'] >= 3 for p in h) / len(h),
                        stops_per_held=sum(p['stops'] for p in h) / len(h), rebound_share=sum(x >= 0.2 for x in rb) / len(rb) if rb else None,
                        premium_median=med([p['prem'] for p in firsts]), premium_20plus=sum(p['prem'] >= 0.2 for p in firsts) / len(firsts) if firsts else None,
                        delay_median=med([p['delay'] for p in firsts]), in_market_median=med([p['in_market'] for p in h]))
    return out


def trap_readings(rows, arms_trades, rng):
    """陷阱段：按建仓月标签的 contrib（跨起点中位）、陷阱段持有天数、具名陷阱；差值按股票整簇自助（对 BASE）。"""
    label_at = {(r['code'], r['month']): r['label'] for r in rows}
    per = {}
    for arm, starts in arms_trades.items():
        by_code = defaultdict(lambda: [0.0] * len(starts))
        days_in = defaultdict(lambda: [0.0] * len(starts))
        for i, (start, cycles) in enumerate(sorted(starts.items())):
            for c in cycles:
                code = c['security_code'].zfill(6)
                if label_at.get((code, c['entry_date'][:7])) == audit.TRAP:
                    by_code[code][i] += float(c['contrib'] or 0)
                    days_in[code][i] += (date.fromisoformat(c['exit_date'] or '2026-08-28') - date.fromisoformat(c['entry_date'])).days
        per[arm] = (by_code, days_in)
    codes = sorted({c for bc, _ in per.values() for c in bc})
    idx = {c: i for i, c in enumerate(codes)}
    n_start = len(sw.DEFAULT_STARTS)

    def matrix(arm, which):
        m = np.zeros((len(codes), n_start))
        for c, v in per[arm][which].items():
            m[idx[c]] = v
        return m
    out = {}
    base_c, base_d = matrix('BASE', 0), matrix('BASE', 1)
    draws = [np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float) for _ in range(1000)]
    for arm in arms_trades:
        mc, md = matrix(arm, 0), matrix(arm, 1)
        stat = lambda m, w=None: float(np.median((m if w is None else m * w[:, None]).sum(axis=0)))
        dc = [stat(mc, w) - stat(base_c, w) for w in draws]
        dd = [stat(md, w) - stat(base_d, w) for w in draws]
        out[arm] = dict(trap_contrib=stat(mc), trap_days=stat(md), d_contrib=stat(mc) - stat(base_c), d_contrib_ci=[float(np.percentile(dc, 5)), float(np.percentile(dc, 95))],
                        d_days=stat(md) - stat(base_d), d_days_ci=[float(np.percentile(dd, 5)), float(np.percentile(dd, 95))])
        out[arm]['flag'] = '陷阱损失扩大' if out[arm]['d_contrib_ci'][1] < 0 else ''
    return out


def main():
    rows, eps = audit.load_answer_key(audit.LABELS)
    cases = audit.load_cases(audit.CASES, eps)
    pv = audit.load_pv(STATES / 'a_share_daily_states_adopted.csv', {(r['code'], r['date']) for r in rows})
    arms_trades = {a: trades_of(a) for a in ARMS}
    bhv.ACTIONS = ACTIONS
    actions = bhv.load_actions()
    series = {}
    for code in {r['code'] for r in rows}:
        prices = bhv.load_ohlcv(code)
        if prices:
            series[code] = ([d for d, _ in prices], total_return_index(prices, actions.get(code, [])))
    last_month = max(r['month'] for r in rows)
    res = dict(execution=execution(rows, eps, pv, arms_trades, series), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260928)),
               strategy={}, flags={})
    for arm, starts in arms_trades.items():
        trades = {k: [dict(code=c['security_code'].zfill(6), entry=c['entry_date'], exit=c['exit_date'], invested=float(c['invested'] or 0),
                           contrib=float(c['contrib'] or 0)) for c in v] for k, v in starts.items()}
        s = audit.strategy_readings(trades, rows, cases, last_month)
        res['strategy'][arm] = dict(by_label=s['by_label'], cases={k: v for k, v in s['cases'].items() if k in TRAP_CASES or k.startswith('O')})
    # 读数标记：每臂与 BASE 合成一份 sweep 文件交 sw.report
    lines = {g: (EXP / f'sweep_{g}.txt').read_text().splitlines() for g in ('full', 'A')}
    for arm in ARMS:
        if arm == 'BASE':
            continue
        text = []
        for g in ('full', 'A'):
            for ln in lines[g][(0 if g == 'full' else 2):]:
                if ln.startswith(('#METRIC', '#MARKET', '#EX5')) or any(ln.startswith(p) for p in
                        (f'{arm}|', f'EX5:{arm}|', f'#WIN5|{arm}|', f'#WIN5|EX5:{arm}|', 'BASE|', 'EX5:BASE|', '#WIN5|BASE|', '#WIN5|EX5:BASE|')):
                    text.append(ln)
        combined = EXP / f'sweep_{arm}.txt'
        combined.write_text('\n'.join(text) + '\n')
        with (EXP / f'report_{arm}.txt').open('w') as f, contextlib.redirect_stdout(f):
            sw.report(combined, f'OI-224 {arm} vs BASE（v4.215 状态、0bp）')
        rep = (EXP / f'report_{arm}.txt').read_text().splitlines()
        at = next((i for i, ln in enumerate(rep) if ln.startswith('【读数标记】')), None)
        import re
        res['flags'][arm] = (re.findall(r'(未见劣化|回撤改善|两表反向|劣化|不可判)', rep[at + 2]) or [''])[:1] if at is not None else ['']
        # 第 11 款案例归因（锚点起点）
        subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/case_attribution.py'),
                        '--base', f"BASE={EXP / 'contrib_BASEfull20111101_trades.csv'}", '--arm', f"{arm}={EXP / f'contrib_{arm}full20111101_trades.csv'}",
                        '--base-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--arm-states', str(STATES / 'a_share_daily_states_adopted.csv'),
                        '--actions', str(ACTIONS), '--out', str(EXP / f'case_{arm}.md')], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    pct = lambda x: '—' if x is None else f'{x * 100:.0f}%'
    out = ['# OI-224 第二批读数（v4.215 状态，含第一批臂重跑）', '', '| 臂 | 从未持有 | ≥3 周期 | 每段止损 | 止损后再涨≥20% | 首买离低点中位 | 首买已涨≥20% | 等待天数 | 在场比例 | 陷阱 contrib Δ（90%） | 陷阱天数 Δ | 读数标记 |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    for arm in ARMS:
        e, t = res['execution'][arm], res['traps'][arm]
        flag = res['flags'].get(arm, [''])
        out.append(f"| {arm} | {pct(e['never_held'])} | {pct(e['churn_3plus'])} | {e['stops_per_held']:.2f} | {pct(e['rebound_share'])} | {pct(e['premium_median'])} | "
                   f"{pct(e['premium_20plus'])} | {e['delay_median']} | {pct(e['in_market_median'])} | {t['d_contrib'] * 100:+.1f}pp [{t['d_contrib_ci'][0] * 100:+.1f}, {t['d_contrib_ci'][1] * 100:+.1f}] {t['flag']} | "
                   f"{t['d_days']:+.0f} | {flag[0] if flag else ''} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
