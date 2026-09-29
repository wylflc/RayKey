"""OI-233 读数（preregister.md 第 1～9 条）：执行读数、第 13 款策略层、陷阱读数、第 11 款案例归因、参考读数与标记、
风险与集中度、退出原因、止损代价诊断。

    python3 readings.py     # → readings.json、readings.md、report_<臂>.txt、case_<臂>.md
"""
import bisect
import contextlib
import csv
import glob
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
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
from run import ACTIONS, ARMS, LINE, STATES  # noqa: E402

CASES = ('O01', 'O02', 'O03', 'O05', 'O08', 'O10', 'T01', 'T02', 'T11')   # 具名案例（preregister 第 2、3 条）
EXITS = (('止损', '止损'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'),
         ('强平', '强平'), ('回测截止', '截止清算'))


def shift(day, months):
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def trades_of(arm):
    out = {}
    for path in sorted(glob.glob(str(EXP / 'trades' / f'{arm}full*_trades.csv'))):
        start = Path(path).name[len(arm) + 4:len(arm) + 12]
        with open(path, newline='', encoding='utf-8') as f:
            out[f'{start[:4]}-{start[4:6]}-{start[6:]}'] = list(csv.DictReader(f))
    assert len(out) == len(sw.DEFAULT_STARTS), (arm, len(out))
    return out


def execution(eps, pv, arms_trades, series):
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
        h = [p for p in pairs if p['held']]
        firsts = [p for p in h if p['prem'] is not None]
        rb = [x for p in h for x in p['reb']]
        out[arm] = dict(episodes=len(recognized), pairs=len(pairs), never_held=1 - len(h) / len(pairs), churn_3plus=sum(p['cycles'] >= 3 for p in h) / len(h),
                        cycles_median=med([p['cycles'] for p in h]), stops_per_held=sum(p['stops'] for p in h) / len(h),
                        rebound_share=sum(x >= 0.2 for x in rb) / len(rb) if rb else None,
                        premium_median=med([p['prem'] for p in firsts]), premium_20plus=sum(p['prem'] >= 0.2 for p in firsts) / len(firsts) if firsts else None,
                        delay_median=med([p['delay'] for p in firsts]), in_market_median=med([p['in_market'] for p in h]))
    return out


def trap_readings(rows, arms_trades, rng):
    """陷阱段：按建仓月标签的 contrib（跨起点中位）、陷阱段持有天数；差值按股票整簇自助（对 BASE）。"""
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


def exits(arms_trades):
    """退出原因：14 起点逐起点的周期数与 contrib 合计，取跨起点中位。"""
    out = {}
    for arm, starts in arms_trades.items():
        n, c = defaultdict(list), defaultdict(list)
        for cycles in starts.values():
            nn, cc = defaultdict(int), defaultdict(float)
            for x in cycles:
                key = next((name for s, name in EXITS if s in x['exit_reason']), '其他')
                nn[key] += 1
                cc[key] += float(x['contrib'] or 0)
            for _, name in (*EXITS, ('', '其他')):
                n[name].append(nn[name]); c[name].append(cc[name])
        days = [int(x['holding_days'] or 0) for cycles in starts.values() for x in cycles]
        out[arm] = dict(count={k: med(v) for k, v in n.items()}, contrib={k: med(v) for k, v in c.items()},
                        cycles=med([len(v) for v in starts.values()]), holding_days_median=med(days))
    return out


def stop_cost(arms_trades, series, label_at):
    """止损代价诊断（本会话 09-29 只读诊断同口径）：止损按 (代码, 清仓日) 去重；清仓日持仓侧 P/V 是否仍在区内；
    其后 12 个月含分红回报及其超出同月末全部区内股票中位的部分；同起点同票重新建仓的间隔与溢价。"""
    pv = defaultdict(list)
    with (STATES / 'a_share_daily_states_hold.csv').open(newline='', encoding='utf-8') as f:
        r = csv.reader(f); h = next(r)
        ic, idt, ipv = h.index('security_code'), h.index('date'), h.index('valuation_ratio')
        for row in r:
            try:
                v = float(row[ipv])
            except ValueError:
                v = None
            pv[row[ic]].append((row[idt], v if v and v > 0 else None))
    pv_days = {c: [d for d, _ in xs] for c, xs in pv.items()}

    def pv_at(code, day):
        ds = pv_days.get(code) or []
        i = bisect.bisect_right(ds, day) - 1
        return pv[code][i][1] if i >= 0 else None
    last_in_month = {}
    for d in sorted({d for ds in pv_days.values() for d in ds}):
        last_in_month[d[:7]] = d
    month_ends = sorted(last_in_month.values())[:-1]
    zone_by_me = defaultdict(list)
    me_set = set(month_ends)
    for code, xs in pv.items():
        for d, v in xs:
            if d in me_set and v is not None and v <= LINE:
                zone_by_me[d].append(code)

    def fwd(code, day, k):
        if code not in series:
            return None
        days, tr = series[code]
        end = shift(day, k)
        if end > days[-1]:
            return None
        i, j = bisect.bisect_right(days, day) - 1, bisect.bisect_right(days, end) - 1
        return tr[days[j]] / tr[days[i]] - 1 if i >= 0 else None
    bench = {}

    def bench_at(me):
        if me not in bench:
            bench[me] = med([fwd(c, me, 12) for c in zone_by_me.get(me, [])])
        return bench[me]
    out = {}
    for arm, starts in arms_trades.items():
        events, re_prem, re_gap, n_paths = {}, [], [], 0
        for start, cycles in starts.items():
            by_code = defaultdict(list)
            for c in cycles:
                by_code[c['security_code'].zfill(6)].append(c)
            for code, cs in by_code.items():
                cs.sort(key=lambda c: c['entry_date'])
                for i, c in enumerate(cs):
                    if '止损' not in c['exit_reason']:
                        continue
                    n_paths += 1
                    events.setdefault((code, c['exit_date']), float(c['return_pct'] or 0))
                    if i + 1 < len(cs) and code in series:
                        days, tr = series[code]
                        a = tr[days[bisect.bisect_right(days, c['exit_date']) - 1]]
                        b = tr[days[bisect.bisect_right(days, cs[i + 1]['entry_date']) - 1]]
                        gap = (date.fromisoformat(cs[i + 1]['entry_date']) - date.fromisoformat(c['exit_date'])).days
                        re_gap.append(gap)
                        if gap <= 365:
                            re_prem.append(b / a - 1)
        recs = []
        for (code, day), ret in events.items():
            v = pv_at(code, day)
            me = month_ends[bisect.bisect_right(month_ends, day) - 1] if month_ends and month_ends[0] <= day else None
            f12 = fwd(code, day, 12)
            b12 = bench_at(me) if me else None
            recs.append(dict(zone=v is not None and v <= LINE, ret=ret, f12=f12, ex=(f12 - b12) if f12 is not None and b12 is not None else None,
                             label=label_at.get((code, me[:7])) if me else None))
        zone = [x for x in recs if x['zone']]
        f12 = [x['f12'] for x in zone if x['f12'] is not None]
        out[arm] = dict(stop_paths=n_paths, stop_events=len(recs), in_zone_share=len(zone) / len(recs) if recs else None,
                        cycle_return_median=med([x['ret'] for x in recs]), f12_median=med(f12),
                        excess12_median=med([x['ex'] for x in zone]), up20_share=(sum(x >= 0.2 for x in f12) / len(f12)) if f12 else None,
                        trap_share=(sum(x['label'] == audit.TRAP for x in zone) / len(zone)) if zone else None,
                        reentry_gap_median=med(re_gap), reentry_premium_median=med(re_prem),
                        reentry_higher_share=(sum(p > 0 for p in re_prem) / len(re_prem)) if re_prem else None)
    return out


def reference(arm):
    """参考读数与读数标记（sw.report 同一套配对）：主读数、复利读数（全样本／A）、回撤与风险。"""
    lines = {g: (EXP / f'sweep_{g}.txt').read_text().splitlines() for g in ('full', 'A')}
    text = []
    for g in ('full', 'A'):
        for ln in lines[g][(0 if g == 'full' else 2):]:
            if ln.startswith(('#METRIC', '#MARKET', '#EX5')) or any(ln.startswith(p) for p in
                    (f'{arm}|', f'EX5:{arm}|', f'#WIN5|{arm}|', f'#WIN5|EX5:{arm}|', 'BASE|', 'EX5:BASE|', '#WIN5|BASE|', '#WIN5|EX5:BASE|')):
                text.append(ln)
    combined = EXP / f'sweep_{arm}.txt'
    combined.write_text('\n'.join(text) + '\n')
    with (EXP / f'report_{arm}.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(combined, f'OI-233 {arm} vs BASE（v4.221 状态、0bp）')
    sw.set_market(sw.scan_market(combined))
    groups, *_ = sw.load_scan(combined)
    full, ex = groups[''], groups[sw.EX5_PREFIX]
    flag, reasons, _ = sw.reading_flags(full, ex, arm)
    pm = lambda arms, key: sw._paired_median(arms, arm, key)
    lvl = lambda key, fn: fn(full[arm][s][key] for s in full[arm])
    return dict(flag=flag, reasons=reasons, main_full=pm(full, sw.WIN5_KEY), main_A=pm(ex, sw.WIN5_KEY),
                cagr_full=pm(full, '年化'), cagr_A=pm(ex, '年化'), mdd_full=pm(full, '最大回撤'), dd5_full=pm(full, '滚动5年回撤中位'),
                p25_full=pm(full, '滚动5年年化P25'), liquidations_max=lvl('强平次数', max), maint_min=lvl('最低担保比例', min),
                buffer_min=lvl('最低股票同跌缓冲', min), mdd_worst=lvl('最大回撤', max), position_median=lvl('平均仓位', statistics.median),
                turnover_median=lvl('年均换手', statistics.median), top1_max_median=lvl('单票权重最大', statistics.median),
                over60_median=lvl('单票超60%天数占比', statistics.median), cagr_level=lvl('年化', statistics.median))


def main():
    rows, eps = audit.load_answer_key(audit.LABELS)
    cases = audit.load_cases(audit.CASES, eps)
    pv = audit.load_pv(STATES / 'a_share_daily_states_adopted.csv', {(r['code'], r['date']) for r in rows})
    arms_trades = {a: trades_of(a) for a in ARMS}
    bhv.ACTIONS = ACTIONS
    actions = bhv.load_actions()
    codes = {r['code'] for r in rows} | {c['security_code'].zfill(6) for st in arms_trades.values() for cs in st.values() for c in cs}
    series = {}
    for code in codes:
        prices = bhv.load_ohlcv(code)
        if prices:
            series[code] = ([d for d, _ in prices], total_return_index(prices, actions.get(code, [])))
    label_at = {(r['code'], r['month']): r['label'] for r in rows}
    last_month = max(r['month'] for r in rows)
    res = dict(line=LINE, execution=execution(eps, pv, arms_trades, series), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260929)),
               exits=exits(arms_trades), stop_cost=stop_cost(arms_trades, series, label_at), strategy={}, reference={})
    for arm, starts in arms_trades.items():
        trades = {k: [dict(code=c['security_code'].zfill(6), entry=c['entry_date'], exit=c['exit_date'], invested=float(c['invested'] or 0),
                           contrib=float(c['contrib'] or 0)) for c in v] for k, v in starts.items()}
        s = audit.strategy_readings(trades, rows, cases, last_month)
        res['strategy'][arm] = dict(by_label=s['by_label'], cases={k: v for k, v in s['cases'].items() if k in CASES})
        if arm == 'BASE':
            continue
        res['reference'][arm] = reference(arm)
        subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/case_attribution.py'),
                        '--base', f"BASE={EXP / 'contrib_BASEfull20111101_trades.csv'}", '--arm', f"{arm}={EXP / f'contrib_{arm}full20111101_trades.csv'}",
                        '--base-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--arm-states', str(STATES / 'a_share_daily_states_adopted.csv'),
                        '--actions', str(ACTIONS), '--out', str(EXP / f'case_{arm}.md')], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x: '—' if x is None or x != x else f'{x * 100:+.2f}'
    out = [f'# OI-233 读数（v4.221 状态，买入线 {LINE}，14 起点）', '',
           '## 一、执行与陷阱', '',
           '| 臂 | 从未持有 | 周期中位 | ≥3 周期 | 每段止损 | 止损后再涨≥20% | 首买离低点中位 | 首买已涨≥20% | 等待天数 | 在场比例 | 陷阱 contrib Δ（90%） | 陷阱天数 Δ |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        e, t = res['execution'][arm], res['traps'][arm]
        out.append(f"| {arm} | {pct(e['never_held'])} | {e['cycles_median']} | {pct(e['churn_3plus'])} | {e['stops_per_held']:.2f} | {pct(e['rebound_share'])} | "
                   f"{pct(e['premium_median'])} | {pct(e['premium_20plus'])} | {e['delay_median']} | {pct(e['in_market_median'])} | "
                   f"{t['d_contrib'] * 100:+.1f}pp [{t['d_contrib_ci'][0] * 100:+.1f}, {t['d_contrib_ci'][1] * 100:+.1f}] {t['flag']} | {t['d_days']:+.0f} |")
    out += ['', '## 二、参考读数与风险（Δ 为对 BASE 的逐起点配对差中位，pp；水平为 14 起点中位或最值）', '',
            '| 臂 | 标记 | 主读数 全／A | 复利 全／A | 滚5 P25 | 滚5回撤 Δ | 全期回撤 Δ | 最深回撤 | 最低担保比例 | 最低同跌缓冲 | 强平次数最多 | 平均仓位 | 换手 | 单票最大权重中位 |',
            '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        if arm == 'BASE':
            continue
        r = res['reference'][arm]
        out.append(f"| {arm} | {r['flag']} | {pp(r['main_full'])}／{pp(r['main_A'])} | {pp(r['cagr_full'])}／{pp(r['cagr_A'])} | {pp(r['p25_full'])} | "
                   f"{pp(r['dd5_full'])} | {pp(r['mdd_full'])} | {pct(r['mdd_worst'], 1)} | {r['maint_min']:.2f} | {pct(r['buffer_min'], 1)} | {r['liquidations_max']:.0f} | "
                   f"{pct(r['position_median'])} | {r['turnover_median']:.2f} | {pct(r['top1_max_median'])} |")
    out += ['', '## 三、止损代价与退出原因', '',
            '| 臂 | 止损（路径／去重） | 区内止损占比 | 止损后 12 月中位 | 超区内同类中位 | 其后陷阱占比 | 一年内重建溢价中位 | 周期数中位 | 持有天数中位 | 止损 contrib | 出名单 contrib | 换仓 contrib | 涨幅减持 contrib |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        s, x = res['stop_cost'][arm], res['exits'][arm]
        out.append(f"| {arm} | {s['stop_paths']}／{s['stop_events']} | {pct(s['in_zone_share'])} | {pct(s['f12_median'], 1)} | {pct(s['excess12_median'], 1)} | "
                   f"{pct(s['trap_share'])} | {pct(s['reentry_premium_median'], 1)} | {x['cycles']} | {x['holding_days_median']} | "
                   f"{pp(x['contrib']['止损'])} | {pp(x['contrib']['出名单'])} | {pp(x['contrib']['换仓'])} | {pp(x['contrib']['涨幅减持'])} |")
    out += ['', '## 四、第 13 款策略层（建仓月标签的 contrib，跨起点中位，pp）', '']
    labels = sorted({k for s in res['strategy'].values() for k in s['by_label']})
    out += ['| 臂 | ' + ' | '.join(labels) + ' |', '| --- |' + ' ---: |' * len(labels)]
    for arm in ARMS:
        bl = res['strategy'][arm]['by_label']
        cell = lambda k: pp(bl[k].get('contrib')) if isinstance(bl.get(k), dict) and bl[k].get('contrib') is not None else '—'
        out.append(f'| {arm} | ' + ' | '.join(cell(k) for k in labels) + ' |')
    names = {c['case_id']: f"{c['security_name']} {c['window_start']}～{c['window_end']}" for c in cases}
    out += ['', '## 五、具名案例（持有过的起点数／可比起点数，contrib 中位 pp）', '',
            '| 臂 | ' + ' | '.join(f'{k} {names.get(k, "")}' for k in CASES) + ' |', '| --- |' + ' ---: |' * len(CASES)]
    for arm in ARMS:
        cs = res['strategy'][arm]['cases']
        out.append(f'| {arm} | ' + ' | '.join(f"{cs[k]['held_starts']}/{cs[k]['starts']}，{pp(cs[k]['contrib_median'])}" if k in cs else '—' for k in CASES) + ' |')
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
