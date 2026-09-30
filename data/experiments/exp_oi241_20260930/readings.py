"""OI-241 读数（preregister.md 第 1～8 条）：已持仓加仓改按建仓条件（A5 一档 5%；A2 买入 2%、卖出 5%）与分解对照 X2
（只把买入一档改为 2%），参照 S15（现行 BASE）。对 S15 的参考读数（全样本／A／U，第 4 款 U 表）、分解（全样本／A／UC）、
加仓账、风险与集中度、逐年、具名个案（中材国际、海螺水泥）、第 13 款、第 11 款、第 12 款。

    python3 snap.py && python3 readings.py     # → readings.json、readings.md、case_<臂>_vs_S15.md
"""
import bisect
import csv
import glob
import gzip
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
from delta_attribution import load_contrib  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from patch import load as load_engine  # noqa: E402
from run import A_SET, ACTIONS, ARMS, LINE, NEW, REF, STATES  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
DECOMP = [('A2', 'X2'), ('X2', REF), ('A5', 'A2')]
YEAR_PAIRS = [('A5', REF), ('A2', REF), ('X2', REF), ('A2', 'X2')]
STOCK_YEAR_PAIRS = [('A5', REF), ('A2', 'X2')]
CASE_PAIRS = [('A5', REF), ('A2', REF)]
CASES = ('O01', 'O02', 'O03', 'O05', 'O08', 'O10', 'T01', 'T02', 'T11')
NAMED = (('600970', '中材国际', '2024-01-01', '2026-12-31'), ('600585', '海螺水泥', '2018-01-01', '2022-12-31'))
EXITS = (('止损', '止损'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'), ('强平', '强平'), ('回测截止', '截止清算'))
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
NAMES = (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv')
CREDIT = 0.666
DEEP = -0.20
FAMILY_BEFORE = 98            # OI-233～OI-240 已试臂数（OI-240 预登记：OI-233～OI-239 共 92 臂，OI-240 新增 6 臂）


def load(path):
    sw.set_market(sw.scan_market(path))
    groups, _orders, failed, *_ = sw.load_scan(path)
    assert not any(failed.values()), (path, failed)
    return groups


FULL = load(EXP / 'sweep_full.txt')['']
EXA = load(EXP / 'sweep_A.txt')[sw.EX5_PREFIX]
EXUC = load(EXP / 'sweep_UC.txt')[sw.EX5_PREFIX]
EXU = {a: load(EXP / 'u' / f'{a}.txt')[sw.EX5_PREFIX] for a in NEW}


def pm(grp, arm, key, ref=REF):
    return sw._paired_median(grp, arm, key, ref=ref)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def share(xs, cond):
    xs = [x for x in xs if x is not None]
    return sum(cond(x) for x in xs) / len(xs) if xs else None


def shift(day, months):
    y, m = int(day[:4]), int(day[5:7]) + months
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return f'{y:04d}-{m:02d}-{min(int(day[8:10]), last):02d}'


def years_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days / 365.25


def tag(arm, start):
    return sw.summary_tag(arm + 'full', start, '')


def contrib_file(arm):
    return EXP / f'contrib_{tag(arm, ANCHOR)}_trades.csv'


def trades_of(arm):
    out = {}
    for s in STARTS:
        with (EXP / 'trades' / f'{tag(arm, s)}_trades.csv').open(newline='', encoding='utf-8') as f:
            out[s] = list(csv.DictReader(f))
    return out


def ledger_of(arm, start):
    p = EXP / 'ledgers' / (f'ledger_{arm}.csv' if start == ANCHOR else f'{tag(arm, start)}.csv')
    with p.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


NAV = {}


def nav_of(arm, start):
    if (arm, start) not in NAV:
        with (EXP / 'nav' / f'{tag(arm, start)}.csv').open(encoding='utf-8') as f:
            NAV[(arm, start)] = {r['date']: (float(r['net_equity']), float(r['debt']), int(r['positions'])) for r in csv.DictReader(f)}
    return NAV[(arm, start)]


def snaps_of(arm, start):
    """逐日持仓 {代码: {日: (股数, 持仓均价, 净资产)}}（snap.py）。"""
    out = defaultdict(dict)
    with gzip.open(EXP / 'snaps' / f'{arm}_{start}.csv.gz', 'rt', newline='') as f:
        for r in csv.DictReader(f):
            out[r['code']][r['date']] = (float(r['shares']), float(r['cost']), float(r['equity']))
    return out


def names():
    out = {}
    for path in NAMES:
        if path.exists():
            for r in csv.DictReader(path.open(encoding='utf-8')):
                if r.get('security_code') and r.get('security_name'):
                    out[r['security_code'].zfill(6)] = r['security_name']
    for p in glob.glob(str(EXP / 'ledgers' / 'ledger_*.csv')):
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r.get('security_name'):
                out.setdefault(r['security_code'].zfill(6), r['security_name'])
    return out


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

    def mindd(self, code, day, k):
        """其后 k 个交易日内总回报指数的最低点相对当日的跌幅。"""
        if code not in self.s:
            return None
        days, tr = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        if i < 0 or i + k >= len(days):
            return None
        return min(tr[days[j]] for j in range(i + 1, i + k + 1)) / tr[days[i]] - 1

    def low(self, code, a, b):
        days, tr = self.s[code]
        seg = days[bisect.bisect_left(days, a):bisect.bisect_right(days, b)]
        return min(tr[d] for d in seg) if seg else None


# ── 参考读数 ─────────────────────────────────────────────────────────────────────────────────────────────

def clause4(arm):
    grp, items, bad = EXU[arm], [], []
    for key, ratio, good in CLAUSE4:
        d = pm(grp, arm, key) * good
        noise, tol = (0.005, 0.033) if ratio else (0.0015, 0.01)
        items.append((key, d))
        if d < -noise:
            bad.append((key, d, d >= -tol))
    return dict(ok=not bad or (len(bad) == 1 and bad[0][2]), bad=[(k, d) for k, d, _ in bad], items=items)


def levels(arm):
    col = lambda key: [FULL[arm][s][key] for s in STARTS]
    out = {k: statistics.median(col(k)) for k in ('年化', '最大回撤', '平均仓位', '年均换手', *CONC)}
    out.update(mdd_worst=max(col('最大回撤')), maint_min=min(col('最低担保比例')), liquidations_max=max(col('强平次数')),
               worst5_min=min(col('滚动5年年化最差')))
    return out


def vs_base(arm):
    flag, reasons, vals = sw.reading_flags(FULL, EXA, arm, ref=REF)
    u = EXU[arm]
    eps = vals['回撤段']
    return dict(flag=flag, reasons=reasons,
                main=[pm(FULL, arm, W5), pm(EXA, arm, W5), pm(u, arm, W5)],
                cagr=[pm(FULL, arm, '年化'), pm(EXA, arm, '年化'), pm(u, arm, '年化')],
                mdd=[pm(FULL, arm, '最大回撤'), pm(EXA, arm, '最大回撤')], dd5=pm(FULL, arm, '滚动5年回撤中位'),
                shallower=sum(ep['delta'] <= -sw.DD_PATH_MDD_GAIN for ep in eps), episodes=len(eps),
                better_starts=sum(FULL[arm][s]['年化'] > FULL[REF][s]['年化'] for s in STARTS), clause4=clause4(arm))


def year_returns(arm):
    out = defaultdict(dict)
    for s in STARTS:
        nav = nav_of(arm, s)
        ye = {}
        for d in sorted(nav):
            ye[d[:4]] = d
        for y in range(2010, 2027):
            p, c = ye.get(str(y - 1)), ye.get(str(y))
            if p and c:
                out[y][s] = nav[c][0] / nav[p][0] - 1
    return out


def year_pair(ya, yr):
    per = {}
    for y in sorted(ya):
        d = [ya[y][s] - yr[y][s] for s in ya[y] if s in yr[y]]
        if d:
            per[y] = dict(median=statistics.median(d), better=sum(x > 0 for x in d), n=len(d))
    return dict(per_year=per, years_pos=sum(v['median'] > 0 for v in per.values()), years=len(per))


def pair(arm, ref, years):
    flag, reasons, _ = sw.reading_flags(FULL, EXA, arm, ref=ref)
    return dict(arm=arm, ref=ref, flag=flag, reasons=reasons,
                main=[pm(FULL, arm, W5, ref), pm(EXA, arm, W5, ref), pm(EXUC, arm, W5, ref)],
                cagr=[pm(FULL, arm, '年化', ref), pm(EXA, arm, '年化', ref), pm(EXUC, arm, '年化', ref)],
                mdd=pm(FULL, arm, '最大回撤', ref), dd5=pm(FULL, arm, '滚动5年回撤中位', ref),
                better_starts=sum(FULL[arm][s]['年化'] > FULL[ref][s]['年化'] for s in STARTS),
                years=year_pair(years[arm], years[ref]))


def stock_years(a, r):
    """detail/ 的逐 (代码, 年) contrib：逐年个股贡献差（整年在场起点平均）与正负前三。"""
    per = {}
    for arm in (a, r):
        for s in STARTS:
            d = json.loads((EXP / 'detail' / f'{tag(arm, s)}.json').read_text())
            y = defaultdict(dict)
            for key, v in d['contrib_year'].items():
                code, yr = key.split('|')
                y[int(yr)][code] = v
            per[(arm, s)] = y
    rows = {}
    for y in range(2010, 2027):
        active = [s for s in STARTS if int(s[:4]) <= y - 1]
        if not active:
            continue
        diff = defaultdict(float)
        for s in active:
            ya, yr = per[(a, s)].get(y, {}), per[(r, s)].get(y, {})
            for code in set(ya) | set(yr):
                diff[code] += (ya.get(code, 0.0) - yr.get(code, 0.0)) / len(active)
        ranked = sorted(diff.items(), key=lambda kv: kv[1])
        rows[y] = dict(n=len(active), total=sum(diff.values()), top=ranked[::-1][:3], bottom=ranked[:3])
    return rows


# ── 加仓账与深度浮亏周期 ─────────────────────────────────────────────────────────────────────────────────

def is_add(x):
    return x['action'] == '买入' and x['reason'].startswith('定投加仓')


def add_account(S, mas, prices):
    """逐起点：加仓笔数与金额（每年，占信号日净资产）、信号日 MA20 ≤ MA60 与收盘 ≤ MA20 的笔数占比；
    逐笔（（代码, 成交日）臂内跨起点去重）：其后 20／60 个交易日含分红总回报、60 日内最深回撤，按信号日 MA20 ≤ MA60 分组。"""
    out, state_of = {}, {}
    for arm in ARMS:
        cnt, cnt_y, amt_y, down_s, below_s = [], [], [], [], []
        uniq = {}
        for s in STARTS:
            nav = nav_of(arm, s)
            days = sorted(nav)
            sig_of = {days[i]: days[i - 1] for i in range(1, len(days))}
            yrs = years_between(days[0], days[-1])
            n = down = below = known = 0
            amt = 0.0
            for x in ledger_of(arm, s):
                if not is_add(x):
                    continue
                code, exe = x['security_code'].zfill(6), x['date']
                sig = sig_of.get(exe)
                n += 1
                if sig in nav and nav[sig][0] > 0:
                    amt += float(x['amount']) / nav[sig][0]
                m, c = mas.get(code, {}).get(sig) or {}, prices.get(code, {}).get(sig)
                if sig and 20 in m and 60 in m and c:
                    known += 1
                    st = (m[20] <= m[60], c <= m[20])
                    down += st[0]
                    below += st[1]
                    uniq.setdefault((code, exe), st)
                    state_of[(arm, s, code, exe)] = st
            cnt.append(n)
            cnt_y.append(n / yrs)
            amt_y.append(amt / yrs)
            down_s.append(down / known if known else None)
            below_s.append(below / known if known else None)
        groups = {}
        for key, want in (('MA20≤MA60', True), ('MA20>MA60', False)):
            xs = [(S.fwd_days(c, e, 20), S.fwd_days(c, e, 60), S.mindd(c, e, 60)) for (c, e), st in uniq.items() if st[0] == want]
            f20 = [a for a, _, _ in xs if a is not None]
            f60 = [b for _, b, _ in xs if b is not None]
            dd = [d for _, _, d in xs if d is not None]
            groups[key] = dict(n=len(xs), f20=med(f20), f20_neg=share(f20, lambda v: v < 0), f60=med(f60),
                               f60_neg=share(f60, lambda v: v < 0), dd10=share(dd, lambda v: v <= -0.10))
        out[arm] = dict(adds=med(cnt), adds_per_year=med(cnt_y), amount_per_year=med(amt_y), down_share=med(down_s),
                        below_share=med(below_s), unique=len(uniq), groups=groups)
    return out, state_of


def segments(held, days):
    """逐票连续持有段 [(首日, 末日)]；held = {日: …}。"""
    idx = {d: i for i, d in enumerate(days)}
    seq = sorted(d for d in held if d in idx)
    out, a, prev = [], None, None
    for d in seq:
        if a is None:
            a = d
        elif idx[d] != idx[prev] + 1:
            out.append((a, prev))
            a = d
        prev = d
    if a is not None:
        out.append((a, prev))
    return out


def deep_cycles(prices):
    """snaps/：持有期内收盘 ÷ 持仓均价 − 1 曾 ≤ −20% 的周期。逐起点计数取中位；最大权重与最深浮亏按（代码, 出场日）臂内跨起点去重后取中位。"""
    out = {}
    for arm in ARMS:
        per_start, pooled = [], {}
        for s in STARTS:
            days = sorted(nav_of(arm, s))
            idx = {d: i for i, d in enumerate(days)}
            n = 0
            for code, held in snaps_of(arm, s).items():
                for a, b in segments(held, days):
                    path = [(prices[code][d] / held[d][1] - 1, held[d][0] * prices[code][d] / held[d][2])
                            for d in days[idx[a]:idx[b] + 1] if prices.get(code, {}).get(d) and held[d][1] > 0 and held[d][2] > 0]
                    if not path or min(p[0] for p in path) > DEEP:
                        continue
                    n += 1
                    exit_day = days[idx[b] + 1] if idx[b] + 1 < len(days) else 'open'
                    pooled.setdefault((code, exit_day), (min(p[0] for p in path), max(p[1] for p in path)))
            per_start.append(n)
        out[arm] = dict(per_start=med(per_start), pooled=len(pooled), min_pnl_median=med([v[0] for v in pooled.values()]),
                        max_weight_median=med([v[1] for v in pooled.values()]))
    return out


def named_cases(prices, arms_trades, state_of):
    """锚点起点：中材国际（2024 起）、海螺水泥（2018～2022）逐臂周期。"""
    out = {}
    days_of = {a: sorted(nav_of(a, ANCHOR)) for a in ARMS}
    for code, name, lo, hi in NAMED:
        rows = {}
        for arm in ARMS:
            held = snaps_of(arm, ANCHOR).get(code, {})
            days = days_of[arm]
            idx = {d: i for i, d in enumerate(days)}
            adds = [x for x in ledger_of(arm, ANCHOR) if x['security_code'].zfill(6) == code and is_add(x)]
            cyc = []
            for c in arms_trades[arm][ANCHOR]:
                if c['security_code'].zfill(6) != code or c['exit_date'] < lo or c['entry_date'] > hi:
                    continue
                inside = [d for d in days if c['entry_date'] <= d <= c['exit_date'] and d in held and prices.get(code, {}).get(d)]
                path = [(prices[code][d] / held[d][1] - 1, held[d][0] * prices[code][d] / held[d][2], held[d][1]) for d in inside if held[d][1] > 0]
                ca = [x for x in adds if c['entry_date'] <= x['date'] <= c['exit_date']]
                cyc.append(dict(entry=c['entry_date'], exit=c['exit_date'], exit_reason=c['exit_reason'][:24], buys=int(c['buys'] or 0),
                                adds=len(ca), adds_down=sum(bool(state_of.get((arm, ANCHOR, code, x['date']), (0, 0))[0]) for x in ca),
                                min_pnl=min((p[0] for p in path), default=None), max_weight=max((p[1] for p in path), default=None),
                                last_cost=path[-1][2] if path else None, contrib=float(c['contrib'] or 0),
                                ret=float(c['return_pct'] or 0)))
            rows[arm] = cyc
        out[code] = dict(name=name, window=[lo, hi], arms=rows)
    return out


# ── 执行、陷阱与行为（OI-237／OI-240 同口径）─────────────────────────────────────────────────────────────

def execution(eps, pv, arms_trades, S):
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
                days, _tr = S.s[e['code']]
                span = (date.fromisoformat(min(e['end'], days[-1])) - date.fromisoformat(e['start'])).days
                cs = [c for c in cycles if c['security_code'].zfill(6) == e['code'] and c['entry_date'] <= e['end'] and c['exit_date'] >= e['start']]
                held = sum((date.fromisoformat(min(c['exit_date'], e['end'])) - date.fromisoformat(max(c['entry_date'], e['start']))).days for c in cs)
                already = any(c['entry_date'] < e['start'] for c in cs)
                first = min((c['entry_date'] for c in cs if c['entry_date'] >= e['start']), default=None)
                prem = delay = None
                if first and not already:
                    lo = S.low(e['code'], e['start'], first)
                    prem, delay = S.at(e['code'], first) / lo - 1, (date.fromisoformat(first) - date.fromisoformat(e['start'])).days
                inb = [(d, a) for d, a in buys.get(e['code'], []) if e['start'] <= d <= e['end']]
                wprem = None
                if inb:
                    lo = S.low(e['code'], e['start'], inb[-1][0])
                    units = sum(a / S.at(e['code'], d) for d, a in inb)
                    wprem = (sum(a for _, a in inb) / units) / lo - 1 if lo and units > 0 else None
                pairs.append(dict(held=bool(cs), cycles=len(cs), prem=prem, delay=delay, wprem=wprem,
                                  in_market=held / span if span > 0 else None))
        h = [p for p in pairs if p['held']]
        firsts = [p for p in h if p['prem'] is not None]
        wp = [p['wprem'] for p in pairs if p['wprem'] is not None]
        out[arm] = dict(never_held=1 - len(h) / len(pairs), churn_3plus=sum(p['cycles'] >= 3 for p in h) / len(h),
                        cycles_median=med([p['cycles'] for p in h]), premium_median=med([p['prem'] for p in firsts]),
                        delay_median=med([p['delay'] for p in firsts]), in_market_median=med([p['in_market'] for p in h]),
                        wprem_median=med(wp), wprem_p75=float(np.percentile(wp, 75)) if wp else None)
    return out


def trap_readings(rows, arms_trades, rng):
    label_at = {(r['code'], r['month']): r['label'] for r in rows}
    per = {}
    for arm, starts in arms_trades.items():
        by_code = defaultdict(lambda: [0.0] * len(starts))
        for i, (_start, cycles) in enumerate(sorted(starts.items())):
            for c in cycles:
                code = c['security_code'].zfill(6)
                if label_at.get((code, c['entry_date'][:7])) == audit.TRAP:
                    by_code[code][i] += float(c['contrib'] or 0)
        per[arm] = by_code
    codes = sorted({c for bc in per.values() for c in bc})
    idx = {c: i for i, c in enumerate(codes)}

    def matrix(arm):
        m = np.zeros((len(codes), len(STARTS)))
        for c, v in per[arm].items():
            m[idx[c]] = v
        return m
    ref = matrix(REF)
    draws = [np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float) for _ in range(1000)]
    stat = lambda m, w=None: float(np.median((m if w is None else m * w[:, None]).sum(axis=0)))
    out = {}
    for arm in arms_trades:
        mc = matrix(arm)
        dc = [stat(mc, w) - stat(ref, w) for w in draws]
        out[arm] = dict(d_contrib=stat(mc) - stat(ref), d_contrib_ci=[float(np.percentile(dc, 5)), float(np.percentile(dc, 95))])
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


def debt_at_line(arm):
    return med([sum(debt >= CREDIT * e - 1 for e, debt, _ in nav.values() if e > 0) / len(nav) for nav in (nav_of(arm, s) for s in STARTS)])


def top3_share(arm, ref):
    a, _ = load_contrib(contrib_file(arm))
    b, _ = load_contrib(contrib_file(ref))
    d = {c: a.get(c, 0.0) - b.get(c, 0.0) for c in set(a) | set(b)}
    total = sum(d.values())
    sign = 1 if total >= 0 else -1
    top = sorted(d.items(), key=lambda kv: -kv[1] * sign)[:3]
    return dict(total=total, top3=[(c, v) for c, v in top], share=sum(v for _, v in top) / total if total else None)


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
    bt = load_engine()
    bt.ACTIONS = ACTIONS
    held_codes = {c['security_code'].zfill(6) for st in arms_trades.values() for cs in st.values() for c in cs}
    closes = bt.load_prices(held_codes)
    ev = bt.load_actions()
    mas = {c: bt.adjusted_moving_averages(closes[c], ev.get(c, {}), (20, 60)) for c in held_codes if c in closes}
    last_month = max(r['month'] for r in rows)
    years = {a: year_returns(a) for a in ARMS}
    nm = names()
    adds, state_of = add_account(S, mas, closes)
    res = dict(line=LINE, ref=REF, A=A_SET, levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in NEW},
               decomp=[pair(a, r, years) for a, r in DECOMP],
               years={f'{a}|{r}': year_pair(years[a], years[r]) for a, r in YEAR_PAIRS},
               stock_years={f'{a}|{r}': stock_years(a, r) for a, r in STOCK_YEAR_PAIRS},
               adds=adds, deep=deep_cycles(closes), named=named_cases(closes, arms_trades, state_of),
               execution=execution(eps, pv, arms_trades, S), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260930)),
               exits=exits(arms_trades), debt_at_line={a: debt_at_line(a) for a in ARMS},
               family=dict(before=FAMILY_BEFORE, new=len(NEW), total=FAMILY_BEFORE + len(NEW)), strategy={}, cases={})
    for arm, starts in arms_trades.items():
        trades = {k: [dict(code=c['security_code'].zfill(6), entry=c['entry_date'], exit=c['exit_date'], invested=float(c['invested'] or 0),
                           contrib=float(c['contrib'] or 0)) for c in v] for k, v in starts.items()}
        s = audit.strategy_readings(trades, rows, cases, last_month)
        res['strategy'][arm] = dict(by_label=s['by_label'], cases={k: v for k, v in s['cases'].items() if k in CASES})
    for arm, ref in CASE_PAIRS:
        out = EXP / f'case_{arm}_vs_{ref}.md'
        subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/case_attribution.py'),
                        '--base', f'{ref}={contrib_file(ref)}', '--arm', f'{arm}={contrib_file(arm)}',
                        '--base-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--arm-states', str(STATES / 'a_share_daily_states_adopted.csv'),
                        '--actions', str(ACTIONS), '--out', str(out)], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        table = [ln for ln in out.read_text(encoding='utf-8').splitlines() if ln.startswith('| ') and 'pp |' in ln][:10]
        res['cases'][f'{arm}|{ref}'] = dict(top3=top3_share(arm, ref), table=table)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, cases, nm)


def write_md(res, cases, nm):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)
    arms = list(ARMS)
    out = [f'# OI-241 读数（v4.221 状态，买入线 {LINE}，14 起点；参照 S15 = 现行 BASE）', '',
           'Δ 均为逐起点配对差中位（pp）。主读数 = 同窗口滚 5 年化配对差；复利读数 = 全期 CAGR 配对差；回撤 Δ 为负 = 更浅。'
           f"A = S15 锚点前五（{'、'.join(nm.get(c, c) for c in A_SET)}）；U = A ∪ 该臂前五；UC = A ∪ 三个新臂前五。"
           'A5 = 已持仓加仓改按建仓条件（近 3 日未创 20 日新低、收盘 > MA5 与 MA20，不要求 MA20 > MA60），一档 5%；'
           'A2 = 同 A5，买入一档 2%、卖出一档 5%；X2 = 分解对照，只把买入一档改为 2%、卖出 5%，加仓仍 MA20 > MA60。读数只作裁定参考。', '',
           '## 一、对 S15 的参考读数', '',
           '| 臂 | 标记 | 主读数 全／A／U | 复利 全／A／U | 第 4 款 U | 年化 | 最大回撤 | 全期回撤 Δ 全／A | 滚5回撤 Δ | 更浅≥5pp 回撤段 | 复利胜出起点 |',
           '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        if arm == REF:
            out.append(f"| {REF}（参照） | — | — | — | — | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | — | — | — | — |")
            continue
        r = res['vs_base'][arm]
        c4 = ('去赢家全面优秀' if r['clause4']['ok'] else '未满足') + ('' if not r['clause4']['bad'] else '（' + '、'.join(
            f"{k} {d * (1 if 'Calmar' in k or 'Sharpe' in k else 100):+.2f}" for k, d in r['clause4']['bad']) + '）')
        out.append(f"| {arm} | {r['flag']} | {trio(r['main'])} | {trio(r['cagr'])} | {c4} | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | "
                   f"{trio(r['mdd'])} | {pp(r['dd5'])} | {r['shallower']}/{r['episodes']} | {r['better_starts']}/14 |")
    out += ['', '### 标记依据', '']
    for arm in NEW:
        out.append(f"- **{arm}**：{res['vs_base'][arm]['flag']}；" + ('；'.join(res['vs_base'][arm]['reasons']) or '—'))
    out += ['', '## 二、分解（全样本／A／UC）', '',
            '| 对比 | 含义 | 标记 | 主读数 全／A／UC | 复利 全／A／UC | 全期回撤 Δ | 滚5回撤 Δ | 复利胜出起点 | 逐年胜出年数 |',
            '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |']
    meaning = {('A2', 'X2'): '只换加仓条件（一档 2%）', ('X2', REF): '只换买入档位 5%→2%', ('A5', 'A2'): '同为建仓条件加仓，档位 5% 对 2%'}
    for p in res['decomp']:
        out.append(f"| {p['arm']} 对 {p['ref']} | {meaning[(p['arm'], p['ref'])]} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | "
                   f"{pp(p['mdd'])} | {pp(p['dd5'])} | {p['better_starts']}/14 | {p['years']['years_pos']}/{p['years']['years']} |")
    out += ['', '## 三、加仓账', '',
            '笔数与金额为逐起点中位（金额 = 加仓成交额 ÷ 信号日净资产，按路径年数年化）；信号日状态用前复权 MA20／MA60 与当日收盘。'
            '逐笔前向读数按（代码, 成交日）臂内跨起点去重，含分红总回报自成交日收盘起算。', '',
            '| 臂 | 加仓笔数 | 每年笔数 | 每年金额占净资产 | 信号日 MA20≤MA60 占比 | 信号日收盘≤MA20 占比 | 去重笔数 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        a = res['adds'][arm]
        out.append(f"| {arm} | {a['adds']:.0f} | {a['adds_per_year']:.1f} | {pct(a['amount_per_year'])} | {pct(a['down_share'])} | "
                   f"{pct(a['below_share'])} | {a['unique']} |")
    out += ['', '| 臂 | 加仓时 | 笔数 | 20 日回报中位 | 20 日为负 | 60 日回报中位 | 60 日为负 | 60 日内最深跌 ≥10% |',
            '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        for key, g in res['adds'][arm]['groups'].items():
            if g['n']:
                out.append(f"| {arm} | {key} | {g['n']} | {pp(g['f20'], 1)} | {pct(g['f20_neg'])} | {pp(g['f60'], 1)} | {pct(g['f60_neg'])} | {pct(g['dd10'])} |")
    out += ['', '### 持有期内曾浮亏 ≥ 20% 的周期（收盘 ÷ 持仓均价 − 1）', '',
            '| 臂 | 逐起点个数中位 | 去重个数 | 最深浮亏中位 | 最大权重中位 |', '| --- | ---: | ---: | ---: | ---: |']
    for arm in arms:
        d = res['deep'][arm]
        out.append(f"| {arm} | {d['per_start']:.0f} | {d['pooled']} | {pct(d['min_pnl_median'], 1)} | {pct(d['max_weight_median'], 1)} |")
    out += ['', '## 四、风险与集中度（14 起点中位；最深回撤、最低担保比例、滚5最差取跨起点极值）', '',
            '| 臂 | 最深回撤 | 滚5最差（最低） | 最低担保比例 | 强平 | 平均仓位 | 换手 | 持仓只数 | 单票权重中位 | 单票最大 | 前三权重 | 单票超60%天数 | 负债到线日 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        out.append(f"| {arm} | {pct(lv['mdd_worst'], 1)} | {pct(lv['worst5_min'], 1)} | {lv['maint_min']:.2f} | {lv['liquidations_max']:.0f} | "
                   f"{pct(lv['平均仓位'])} | {lv['年均换手']:.2f} | {lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | {pct(lv['单票权重最大'])} | "
                   f"{pct(lv['前三权重中位'])} | {pct(lv['单票超60%天数占比'], 1)} | {pct(res['debt_at_line'][arm])} |")
    out += ['', '## 五、逐年', '', '### 逐年配对差（整年在场的起点，中位 pp；括号内为胜出起点数／起点数；2026 截至末次净值日）', '']
    yrs = sorted({int(y) for v in res['years'].values() for y in v['per_year']})
    out += ['| 对比 | ' + ' | '.join(str(y) for y in yrs) + ' | 胜出年数 |', '| --- |' + ' ---: |' * (len(yrs) + 1)]
    for k, v in res['years'].items():
        cells = [f"{pp(v['per_year'][y]['median'], 1)}（{v['per_year'][y]['better']}/{v['per_year'][y]['n']}）" if y in v['per_year'] else '—' for y in yrs]
        out.append(f"| {k.replace('|', ' 对 ')} | " + ' | '.join(cells) + f" | {v['years_pos']}/{v['years']} |")
    fmt = lambda xs: '、'.join(f"{nm.get(c, c)} {v * 100:+.1f}" for c, v in xs if abs(v) >= 0.005) or '—'
    for k, rows in res['stock_years'].items():
        a, r = k.split('|')
        out += ['', f'### 逐年个股贡献差：{a} 对 {r}（整年在场起点平均，pp）', '', '| 年 | 合计 | 多赚前三 | 少赚前三 |', '| --- | ---: | --- | --- |']
        for y, v in rows.items():
            out.append(f"| {y} | {v['total'] * 100:+.1f} | {fmt(v['top'])} | {fmt(v['bottom'])} |")
    out += ['', f'## 六、具名个案（锚点起点 {ANCHOR}）', '']
    for code, c in res['named'].items():
        out += [f"### {c['name']}（{code}，{c['window'][0][:7]}～{c['window'][1][:7]}）", '',
                '| 臂 | 建仓 | 清仓 | 加仓笔数（其中 MA20≤MA60） | 最大权重 | 最深浮亏 | 末日均价 | 周期收益 | contrib pp | 退出 |',
                '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
        for arm in arms:
            for y in c['arms'][arm] or [None]:
                if y is None:
                    out.append(f'| {arm} | 未持有 | | | | | | | | |')
                    continue
                cost = '—' if y['last_cost'] is None else f"{y['last_cost']:.2f}"
                out.append(f"| {arm} | {y['entry']} | {y['exit']} | {y['adds']}（{y['adds_down']}） | {pct(y['max_weight'], 1)} | {pct(y['min_pnl'], 1)} | "
                           f"{cost} | {pct(y['ret'], 1)} | {pp(y['contrib'], 1)} | {y['exit_reason']} |")
        out.append('')
    out += ['## 七、执行与陷阱（陷阱 contrib Δ 对 S15，股票整簇自助 90%）', '',
            '| 臂 | 从未持有 | 周期中位 | ≥3 周期 | 首买离低点中位 | 等待天数 | 在场比例 | 成本加权均价离低点 中位／P75 | 陷阱 contrib Δ（90%） |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        e, t = res['execution'][arm], res['traps'][arm]
        out.append(f"| {arm} | {pct(e['never_held'])} | {e['cycles_median']} | {pct(e['churn_3plus'])} | {pct(e['premium_median'])} | "
                   f"{e['delay_median']} | {pct(e['in_market_median'])} | {pct(e['wprem_median'])}／{pct(e['wprem_p75'])} | "
                   f"{t['d_contrib'] * 100:+.1f}pp [{t['d_contrib_ci'][0] * 100:+.1f}, {t['d_contrib_ci'][1] * 100:+.1f}] {t['flag']} |")
    out += ['', '## 八、第 13 款策略层（建仓月标签的 contrib，跨起点中位，pp）', '']
    labels = sorted({k for s in res['strategy'].values() for k in s['by_label']})
    out += ['| 臂 | ' + ' | '.join(labels) + ' |', '| --- |' + ' ---: |' * len(labels)]
    for arm in arms:
        bl = res['strategy'][arm]['by_label']
        out.append(f'| {arm} | ' + ' | '.join(pp(bl[k]['contrib']) if isinstance(bl.get(k), dict) and bl[k].get('contrib') is not None else '—'
                                              for k in labels) + ' |')
    cn = {c['case_id']: f"{c['security_name']} {c['window_start']}～{c['window_end']}" for c in cases}
    out += ['', '### 具名案例（持有过的起点数／可比起点数，contrib 中位 pp）', '',
            '| 臂 | ' + ' | '.join(f'{k} {cn.get(k, "")}' for k in CASES) + ' |', '| --- |' + ' ---: |' * len(CASES)]
    for arm in arms:
        cs = res['strategy'][arm]['cases']
        out.append(f'| {arm} | ' + ' | '.join(f"{cs[k]['held_starts']}/{cs[k]['starts']}，{pp(cs[k]['contrib_median'])}" if k in cs else '—'
                                              for k in CASES) + ' |')
    out += ['', f'## 九、第 11 款案例归因（锚点起点 {ANCHOR}；全表见 case_<臂>_vs_S15.md）', '']
    for k, v in res['cases'].items():
        t3 = v['top3']
        out += [f"### {k.replace('|', ' 对 ')}：总差 {pp(t3['total'], 1)}pp，前三只 " + '、'.join(f'{nm.get(c, c)} {pp(x, 1)}' for c, x in t3['top3'])
                + f"，净额占比 {pct(t3['share'])}", '', '| 公司 | Δ | 归类 | 依据 |', '| --- | ---: | --- | --- |', *v['table'], '']
    out += ['## 十、退出（14 起点中位：周期数／contrib pp）', '',
            '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' |',
            '| --- | ---: | ---: |' + ' ---: |' * len(EXITS)]
    for arm in arms:
        x = res['exits'][arm]
        out.append(f"| {arm} | {x['cycles']} | {x['holding_days_median']} | " + ' | '.join(f"{x['count'][n]:.0f}／{pp(x['contrib'][n], 1)}" for _, n in EXITS) + ' |')
    f = res['family']
    out += ['', f"## 十一、第 12 款：本族（OI-233 起的执行层研究）已试 {f['before']} 臂，本批新增 {f['new']} 臂，合计 {f['total']} 臂。", '']
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out[:30]))


if __name__ == '__main__':
    main()
