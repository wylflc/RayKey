"""OI-235 读数（preregister.md 第 1～10 条），参照臂 BTNS：执行读数（含机会段成本加权均价离低点）、第 13 款策略层、
陷阱读数、第 11 款案例归因、参考读数与标记、风险与集中度、退出原因、B 做 T 账、C 过线卖出账。

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
from datetime import date, timedelta
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
sys.path.insert(0, str(EXP))
import build_historical_valuation_bands as bhv  # noqa: E402
import opportunity_trap_audit as audit  # noqa: E402
import sweep_backtest_configs as sw  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from run import ACTIONS, ARMS, LINE, REF, STATES  # noqa: E402

CASES = ('O01', 'O02', 'O03', 'O05', 'O08', 'O10', 'T01', 'T02', 'T11')
EXITS = (('P/V≥', '估值减持'), ('止损', '止损'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'),
         ('强平', '强平'), ('回测截止', '截止清算'))
B_ARMS = ('S10', 'S15', 'S20', 'E5', 'S15T5', 'S15T20', 'S15T20b')
C_ARMS = ('V', 'VF')
CREDIT = 0.666


def shift(day, months):
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def tag(arm, start):
    return sw.summary_tag(arm + 'full', start, '')


def trades_of(arm):
    out = {}
    for s in sw.DEFAULT_STARTS:
        with (EXP / 'trades' / f'{tag(arm, s)}_trades.csv').open(newline='', encoding='utf-8') as f:
            out[s] = list(csv.DictReader(f))
    return out


def ledger_of(arm, start):
    p = EXP / 'ledgers' / (f'ledger_{arm}.csv' if start == sw.EX5_ANCHOR_START else f'{tag(arm, start)}.csv')
    with p.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def nav_of(arm, start):
    with (EXP / 'nav' / f'{tag(arm, start)}.csv').open(encoding='utf-8') as f:
        return {r['date']: (float(r['net_equity']), float(r['debt']), int(r['positions'])) for r in csv.DictReader(f)}


class Series:
    """含分红再投总回报指数，按交易日查询与前移。"""

    def __init__(self, series):
        self.s = series

    def at(self, code, day):
        days, tr = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        return tr[days[i]] if i >= 0 else None

    def fwd_days(self, code, day, k):
        if code not in self.s:
            return None
        days, tr = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        if i < 0 or i + k >= len(days):
            return None
        return tr[days[i + k]] / tr[days[i]] - 1

    def fwd_months(self, code, day, k):
        if code not in self.s:
            return None
        days, tr = self.s[code]
        end = shift(day, k)
        if end > days[-1]:
            return None
        i, j = bisect.bisect_right(days, day) - 1, bisect.bisect_right(days, end) - 1
        return tr[days[j]] / tr[days[i]] - 1 if i >= 0 else None

    def low(self, code, a, b):
        days, tr = self.s[code]
        seg = days[bisect.bisect_left(days, a):bisect.bisect_right(days, b)]
        return min(tr[d] for d in seg) if seg else None


def execution(eps, pv, arms_trades, S):
    """`execution_gap.py` 同口径，另加机会段内全部买入的成本加权均价离低点（逐笔流水）。"""
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
        for start, cycles in starts.items():
            buys = defaultdict(list)
            for x in ledger_of(arm, start):
                if x['action'] == '买入':
                    buys[x['security_code'].zfill(6)].append((x['date'], float(x['amount'])))
            for e in recognized:
                if e['code'] not in S.s or start > e['start']:
                    continue
                days, tr = S.s[e['code']]
                span = (date.fromisoformat(min(e['end'], days[-1])) - date.fromisoformat(e['start'])).days
                cs = [c for c in cycles if c['security_code'].zfill(6) == e['code'] and c['entry_date'] <= e['end'] and c['exit_date'] >= e['start']]
                held = sum((date.fromisoformat(min(c['exit_date'], e['end'])) - date.fromisoformat(max(c['entry_date'], e['start']))).days for c in cs)
                stops = [c for c in cs if '止损' in c['exit_reason']]
                already = any(c['entry_date'] < e['start'] for c in cs)
                first = min((c['entry_date'] for c in cs if c['entry_date'] >= e['start']), default=None)
                prem = delay = None
                if first and not already:
                    lo = S.low(e['code'], e['start'], first)
                    prem, delay = S.at(e['code'], first) / lo - 1, (date.fromisoformat(first) - date.fromisoformat(e['start'])).days
                inb = [(d, a) for d, a in buys.get(e['code'], []) if e['start'] <= d <= e['end']]
                wprem = amount = None
                if inb:
                    lo = S.low(e['code'], e['start'], inb[-1][0])
                    units = sum(a / S.at(e['code'], d) for d, a in inb)
                    amount = sum(a for _, a in inb)
                    wprem = (amount / units) / lo - 1 if lo and units > 0 else None
                pairs.append(dict(held=bool(cs), cycles=len(cs), stops=len(stops), prem=prem, delay=delay, wprem=wprem,
                                  in_market=held / span if span > 0 else None))
        h = [p for p in pairs if p['held']]
        firsts = [p for p in h if p['prem'] is not None]
        wp = [p['wprem'] for p in pairs if p['wprem'] is not None]
        out[arm] = dict(episodes=len(recognized), pairs=len(pairs), never_held=1 - len(h) / len(pairs),
                        churn_3plus=sum(p['cycles'] >= 3 for p in h) / len(h), cycles_median=med([p['cycles'] for p in h]),
                        premium_median=med([p['prem'] for p in firsts]),
                        premium_20plus=sum(p['prem'] >= 0.2 for p in firsts) / len(firsts) if firsts else None,
                        delay_median=med([p['delay'] for p in firsts]), in_market_median=med([p['in_market'] for p in h]),
                        wprem_median=med(wp), wprem_p75=float(np.percentile(wp, 75)) if wp else None,
                        wprem_40plus=sum(x >= 0.4 for x in wp) / len(wp) if wp else None)
    return out


def trap_readings(rows, arms_trades, rng):
    """陷阱段：按建仓月标签的 contrib（跨起点中位）、持有天数；对参照臂的差值按股票整簇自助。"""
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
    ref_c, ref_d = matrix(REF, 0), matrix(REF, 1)
    draws = [np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float) for _ in range(1000)]
    for arm in arms_trades:
        mc, md = matrix(arm, 0), matrix(arm, 1)
        stat = lambda m, w=None: float(np.median((m if w is None else m * w[:, None]).sum(axis=0)))
        dc = [stat(mc, w) - stat(ref_c, w) for w in draws]
        dd = [stat(md, w) - stat(ref_d, w) for w in draws]
        out[arm] = dict(trap_contrib=stat(mc), trap_days=stat(md), d_contrib=stat(mc) - stat(ref_c),
                        d_contrib_ci=[float(np.percentile(dc, 5)), float(np.percentile(dc, 95))],
                        d_days=stat(md) - stat(ref_d), d_days_ci=[float(np.percentile(dd, 5)), float(np.percentile(dd, 95))])
        out[arm]['flag'] = '陷阱损失扩大' if out[arm]['d_contrib_ci'][1] < 0 else ''
    return out


def exits(arms_trades):
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
                n[name].append(nn[name])
                c[name].append(cc[name])
        days = [int(x['holding_days'] or 0) for cycles in starts.values() for x in cycles]
        out[arm] = dict(count={k: med(v) for k, v in n.items()}, contrib={k: med(v) for k, v in c.items()},
                        cycles=med([len(v) for v in starts.values()]), holding_days_median=med(days))
    return out


def reference(arm):
    """参考读数与读数标记（sw 同一套配对，ref = 参照臂）；另报对 BASE 的复利读数。报表文件把参照臂改标为 BASE 以复用 sw.report。"""
    lines = {g: (EXP / f'sweep_{g}.txt').read_text().splitlines() for g in ('full', 'A')}
    text = []
    for g in ('full', 'A'):
        for ln in lines[g][(0 if g == 'full' else 2):]:
            if ln.startswith(('#METRIC', '#MARKET', '#EX5')):
                text.append(ln)
                continue
            for lab in (arm, REF):
                for pre in (f'{lab}|', f'EX5:{lab}|', f'#WIN5|{lab}|', f'#WIN5|EX5:{lab}|'):
                    if ln.startswith(pre):
                        text.append(ln.replace(f'{REF}|', 'BASE|', 1) if lab == REF else ln)
    combined = EXP / f'sweep_{arm}.txt'
    combined.write_text('\n'.join(dict.fromkeys(text)) + '\n')
    with (EXP / f'report_{arm}.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(combined, f'OI-235 {arm} vs BTNS（报表中 BASE 即参照臂 BTNS；v4.221 状态、0bp）')
    both = EXP / 'sweep_all.txt'
    sw.set_market(sw.scan_market(both))
    groups, *_ = sw.load_scan(both)
    full, ex = groups[''], groups[sw.EX5_PREFIX]
    flag, reasons, _ = sw.reading_flags(full, ex, arm, ref=REF)
    pm = lambda arms, key, ref=REF: sw._paired_median(arms, arm, key, ref=ref)
    lvl = lambda key, fn: fn(full[arm][s][key] for s in full[arm])
    return dict(flag=flag, reasons=reasons, main_full=pm(full, sw.WIN5_KEY), main_A=pm(ex, sw.WIN5_KEY),
                cagr_full=pm(full, '年化'), cagr_A=pm(ex, '年化'), cagr_vs_base=pm(full, '年化', 'BASE'),
                mdd_full=pm(full, '最大回撤'), dd5_full=pm(full, '滚动5年回撤中位'), p25_full=pm(full, '滚动5年年化P25'),
                liquidations_max=lvl('强平次数', max), maint_min=lvl('最低担保比例', min), buffer_min=lvl('最低股票同跌缓冲', min),
                mdd_worst=lvl('最大回撤', max), position_median=lvl('平均仓位', statistics.median),
                turnover_median=lvl('年均换手', statistics.median), top1_max_median=lvl('单票权重最大', statistics.median),
                holdings_median=lvl('持仓数中位', statistics.median), cagr_level=lvl('年化', statistics.median),
                mdd_level=lvl('最大回撤', statistics.median))


def t_account(S):
    """B 做 T 账：让位减仓（tlog trim）、买回配对（match）；价差收益 ÷ 买回日净资产；减仓后 20／60 个交易日走势。"""
    out = {}
    for arm in B_ARMS:
        per = defaultdict(list)
        f20, f60, sold_gain60 = [], [], []
        dedup = set()
        for s in sw.DEFAULT_STARTS:
            log = json.loads((EXP / 'tlog' / f'{tag(arm, s)}.json').read_text())
            nav = nav_of(arm, s)
            trims = [x for x in log if x[0] == 'trim']
            matches = [x for x in log if x[0] == 'match']
            per['trims'].append(len(trims))
            per['trim_amount_pp'].append(sum(x[3] * x[4] / nav[x[2]][0] for x in trims if x[2] in nav))
            tsh = sum(x[4] for x in trims)
            per['bought_back_share'].append(sum(m[4] for m in matches) / tsh if tsh else None)
            per['t_gain_pp'].append(sum((m[3] - m[6]) * m[4] / nav[m[5]][0] for m in matches if m[5] in nav))
            per['matches'].append(len(matches))
            for x in trims:
                dedup.add((x[1], x[2]))
                a, b = S.fwd_days(x[1], x[2], 20), S.fwd_days(x[1], x[2], 60)
                f20.append(a)
                f60.append(b)
                if b is not None and x[2] in nav:
                    sold_gain60.append(-b * x[3] * x[4] / nav[x[2]][0])
            if matches:
                per['buyback_discount'].append(med([m[6] / m[3] - 1 for m in matches]))
        out[arm] = dict(trims_median=med(per['trims']), trims_dedup=len(dedup), trim_amount_pp=med(per['trim_amount_pp']),
                        bought_back_share=med(per['bought_back_share']), t_gain_pp=med(per['t_gain_pp']),
                        matches_median=med(per['matches']), buyback_discount=med(per['buyback_discount']),
                        fwd20_median=med(f20), fwd60_median=med(f60),
                        fwd60_up10=sum(x > 0.10 for x in f60 if x is not None) / max(1, sum(x is not None for x in f60)),
                        fwd60_down10=sum(x < -0.10 for x in f60 if x is not None) / max(1, sum(x is not None for x in f60)),
                        sold_vs_hold60_pp=sum(sold_gain60) / len(sw.DEFAULT_STARTS))
    return out


def c_account(S, zone_by_me, month_ends):
    """C 过线卖出账：逐笔流水里 `P/V≥` 卖出；其后 20／60／250 个交易日回报，12 个月对同月末区内中位的超额；再买入间隔与溢价。"""
    bench = {}

    def bench_at(me):
        if me not in bench:
            bench[me] = med([S.fwd_months(c, me, 12) for c in zone_by_me.get(me, [])])
        return bench[me]
    out = {}
    for arm in C_ARMS:
        n, f20, f60, f250, ex12, gap, prem, events = [], [], [], [], [], [], [], set()
        for s in sw.DEFAULT_STARTS:
            led = ledger_of(arm, s)
            sells = [x for x in led if x['action'] == '卖出' and 'P/V≥' in x['reason']]
            n.append(len(sells))
            buys = defaultdict(list)
            for x in led:
                if x['action'] == '买入':
                    buys[x['security_code'].zfill(6)].append(x['date'])
            for x in sells:
                code, d = x['security_code'].zfill(6), x['date']
                if (code, d) in events:
                    continue
                events.add((code, d))
                f20.append(S.fwd_days(code, d, 20))
                f60.append(S.fwd_days(code, d, 60))
                f250.append(S.fwd_days(code, d, 250))
                i = bisect.bisect_right(month_ends, d) - 1
                if i >= 0 and (a := S.fwd_months(code, month_ends[i], 12)) is not None and (b := bench_at(month_ends[i])) is not None:
                    ex12.append(a - b)
                nxt = [b_ for b_ in buys[code] if b_ > d]
                if nxt and code in S.s:
                    gap.append((date.fromisoformat(nxt[0]) - date.fromisoformat(d)).days)
                    prem.append(S.at(code, nxt[0]) / S.at(code, d) - 1)
        out[arm] = dict(sells_median=med(n), events=len(events), fwd20=med(f20), fwd60=med(f60), fwd250=med(f250),
                        excess12=med(ex12), excess12_pos=sum(x > 0 for x in ex12) / len(ex12) if ex12 else None,
                        rebuy_gap=med(gap), rebuy_premium=med(prem), rebuy_share=len(gap) / len(events) if events else None)
    return out


def debt_at_line(arm):
    shares = []
    for s in sw.DEFAULT_STARTS:
        nav = nav_of(arm, s)
        shares.append(sum(debt >= CREDIT * e - 1 for e, debt, _ in nav.values() if e > 0) / len(nav))
    return med(shares)


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
    S = Series(series)
    zone_by_me = defaultdict(list)
    for (code, d), v in pv.items():
        if v is not None and v <= LINE:
            zone_by_me[d].append(code)
    month_ends = sorted({r['date'] for r in rows})
    last_month = max(r['month'] for r in rows)
    lines = {g: (EXP / f'sweep_{g}.txt').read_text().splitlines() for g in ('full', 'A')}
    (EXP / 'sweep_all.txt').write_text('\n'.join(lines['full'] + [ln for ln in lines['A'] if not ln.startswith(('#METRIC', '#MARKET'))]) + '\n')
    res = dict(line=LINE, ref=REF, execution=execution(eps, pv, arms_trades, S), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260929)),
               exits=exits(arms_trades), t_account=t_account(S), c_account=c_account(S, zone_by_me, month_ends),
               debt_at_line={a: debt_at_line(a) for a in ARMS}, strategy={}, reference={})
    for arm, starts in arms_trades.items():
        trades = {k: [dict(code=c['security_code'].zfill(6), entry=c['entry_date'], exit=c['exit_date'], invested=float(c['invested'] or 0),
                           contrib=float(c['contrib'] or 0)) for c in v] for k, v in starts.items()}
        s = audit.strategy_readings(trades, rows, cases, last_month)
        res['strategy'][arm] = dict(by_label=s['by_label'], cases={k: v for k, v in s['cases'].items() if k in CASES})
        if arm == REF:
            continue
        res['reference'][arm] = reference(arm)
        subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/case_attribution.py'),
                        '--base', f"{REF}={EXP / f'contrib_{REF}full20111101_trades.csv'}", '--arm', f"{arm}={EXP / f'contrib_{arm}full20111101_trades.csv'}",
                        '--base-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--arm-states', str(STATES / 'a_share_daily_states_adopted.csv'),
                        '--actions', str(ACTIONS), '--out', str(EXP / f'case_{arm}.md')], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, cases)


def write_md(res, cases):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    arms = list(ARMS)
    out = [f'# OI-235 读数（v4.221 状态，买入线 {LINE}，14 起点；参照臂 {REF}）', '',
           'Δ 均为对 BTNS 的逐起点配对差中位（pp），另列对 BASE 的复利读数作参照。读数只作裁定参考。', '',
           '## 一、参考读数与风险', '',
           '| 臂 | 标记 | 主读数 全／A | 复利 全／A | 复利对 BASE | 年化 | 最大回撤 | 滚5 P25 | 滚5回撤 Δ | 全期回撤 Δ | 最深回撤 | 最低担保比例 | 强平 | 平均仓位 | 换手 | 持仓只数 | 负债到线日 |',
           '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        if arm == REF:
            continue
        r = res['reference'][arm]
        out.append(f"| {arm} | {r['flag']} | {pp(r['main_full'])}／{pp(r['main_A'])} | {pp(r['cagr_full'])}／{pp(r['cagr_A'])} | {pp(r['cagr_vs_base'])} | "
                   f"{pct(r['cagr_level'], 1)} | {pct(r['mdd_level'], 1)} | {pp(r['p25_full'])} | {pp(r['dd5_full'])} | {pp(r['mdd_full'])} | "
                   f"{pct(r['mdd_worst'], 1)} | {r['maint_min']:.2f} | {r['liquidations_max']:.0f} | {pct(r['position_median'])} | "
                   f"{r['turnover_median']:.2f} | {r['holdings_median']:.0f} | {pct(res['debt_at_line'][arm])} |")
    out.append(f"| {REF}（参照） | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | {pct(res['debt_at_line'][REF])} |")
    out += ['', '## 二、执行与陷阱', '',
            '| 臂 | 从未持有 | 周期中位 | ≥3 周期 | 首买离低点中位 | 首买已涨≥20% | 等待天数 | 在场比例 | 成本加权均价离低点 中位／P75 | 均价离低点≥40% | 陷阱 contrib Δ（90%） |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        e, t = res['execution'][arm], res['traps'][arm]
        out.append(f"| {arm} | {pct(e['never_held'])} | {e['cycles_median']} | {pct(e['churn_3plus'])} | {pct(e['premium_median'])} | {pct(e['premium_20plus'])} | "
                   f"{e['delay_median']} | {pct(e['in_market_median'])} | {pct(e['wprem_median'])}／{pct(e['wprem_p75'])} | {pct(e['wprem_40plus'])} | "
                   f"{t['d_contrib'] * 100:+.1f}pp [{t['d_contrib_ci'][0] * 100:+.1f}, {t['d_contrib_ci'][1] * 100:+.1f}] {t['flag']} |")
    out += ['', '## 三、第 13 款策略层（建仓月标签的 contrib，跨起点中位，pp）', '']
    labels = sorted({k for s in res['strategy'].values() for k in s['by_label']})
    out += ['| 臂 | ' + ' | '.join(labels) + ' |', '| --- |' + ' ---: |' * len(labels)]
    for arm in arms:
        bl = res['strategy'][arm]['by_label']
        cell = lambda k: pp(bl[k].get('contrib')) if isinstance(bl.get(k), dict) and bl[k].get('contrib') is not None else '—'
        out.append(f'| {arm} | ' + ' | '.join(cell(k) for k in labels) + ' |')
    names = {c['case_id']: f"{c['security_name']} {c['window_start']}～{c['window_end']}" for c in cases}
    out += ['', '## 四、具名案例（持有过的起点数／可比起点数，contrib 中位 pp）', '',
            '| 臂 | ' + ' | '.join(f'{k} {names.get(k, "")}' for k in CASES) + ' |', '| --- |' + ' ---: |' * len(CASES)]
    for arm in arms:
        cs = res['strategy'][arm]['cases']
        out.append(f'| {arm} | ' + ' | '.join(f"{cs[k]['held_starts']}/{cs[k]['starts']}，{pp(cs[k]['contrib_median'])}" if k in cs else '—' for k in CASES) + ' |')
    out += ['', '## 五、退出原因（周期数中位／contrib 中位 pp）', '',
            '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' |', '| --- | ---: | ---: |' + ' ---: |' * len(EXITS)]
    for arm in arms:
        x = res['exits'][arm]
        out.append(f"| {arm} | {x['cycles']} | {x['holding_days_median']} | "
                   + ' | '.join(f"{x['count'][n]:.0f}／{pp(x['contrib'][n], 1)}" for _, n in EXITS) + ' |')
    out += ['', '## 六、B 做 T 账（全样本 14 起点）', '',
            '减仓金额与价差收益 ÷ 当日净资产（pp，逐起点合计取中位）；「卖出对持有 60 日」= Σ(−减仓后 60 日回报 × 减仓金额 ÷ 净资产) ÷ 起点数，正为卖对。', '',
            '| 臂 | 让位减仓次数（中位／去重） | 减仓金额 pp | 买回占所减股数 | 买回价对减仓价 | 做 T 价差收益 pp | 减仓后 20 日 | 减仓后 60 日 | 60 日再涨 >10% | 60 日跌 >10% | 卖出对持有 60 日 pp |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in B_ARMS:
        t = res['t_account'][arm]
        out.append(f"| {arm} | {t['trims_median']:.0f}／{t['trims_dedup']} | {pp(t['trim_amount_pp'], 1)} | {pct(t['bought_back_share'])} | "
                   f"{pct(t['buyback_discount'], 1)} | {pp(t['t_gain_pp'], 2)} | {pct(t['fwd20_median'], 1)} | {pct(t['fwd60_median'], 1)} | "
                   f"{pct(t['fwd60_up10'])} | {pct(t['fwd60_down10'])} | {pp(t['sold_vs_hold60_pp'], 2)} |")
    out += ['', '## 七、C 过线卖出账（全样本 14 起点，按（代码, 日）去重）', '',
            '| 臂 | 卖出笔数中位 | 去重事件 | 其后 20 日 | 60 日 | 250 日 | 12 月超区内中位 | 超额为正 | 再买入占比 | 再买入间隔中位（天） | 再买入溢价 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in C_ARMS:
        c = res['c_account'][arm]
        out.append(f"| {arm} | {c['sells_median']:.0f} | {c['events']} | {pct(c['fwd20'], 1)} | {pct(c['fwd60'], 1)} | {pct(c['fwd250'], 1)} | "
                   f"{pp(c['excess12'], 1)} | {pct(c['excess12_pos'])} | {pct(c['rebuy_share'])} | {c['rebuy_gap']} | {pct(c['rebuy_premium'], 1)} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
