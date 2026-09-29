"""OI-240 读数（preregister.md 第 1～5 条）：CC 已持仓触发的仓位门槛（未到净资产 10／20／30／40／50／60% 才可触发）。
门槛剂量（新臂对 S15、对 CCS15，全样本／A／UC 与逐年）、对 BASE 的叠加读数（全样本／A／U，第 4 款 U 表标记）、换仓与集中度账、
奥特维 2026 案例、逐年个股贡献差、第 13 款、第 11 款案例归因、执行与行为。

    python3 readings.py     # → readings.json、readings.md、case_<臂>_vs_<参照>.md
"""
import bisect
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
from delta_attribution import load_contrib  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from run import ACTIONS, ARMS, LINE, NEW, PARENT, REF, STATES  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
PCTS = (10, 20, 30, 40, 50, 60)
EXTRA_PAIRS = [(f'CC{p}', 'CCS15') for p in PCTS]                 # 设门槛对不设门槛
YEAR_PAIRS = [('CC30', 'S15'), ('CC60', 'S15'), ('CCS15', 'S15'), ('CC60', 'CCS15'), ('CC30', REF), ('CC60', REF)]
STOCK_YEAR_PAIRS = [('CC30', 'S15'), ('CCS15', 'CC60')]
CASE_PAIRS = [('CC30', 'S15'), ('CC60', 'S15'), ('CCS15', 'CC60')]
CASE_ARMS = ('S15', 'CCS15', 'CC30', 'CC60')
AOTEWEI = '688516'
CASES = ('O01', 'O02', 'O03', 'O05', 'O08', 'O10', 'T01', 'T02', 'T11')
EXITS = (('止损', '止损'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'), ('强平', '强平'), ('回测截止', '截止清算'))
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
NAMES = (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv')
CREDIT = 0.666


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


def nav_of(arm, start):
    with (EXP / 'nav' / f'{tag(arm, start)}.csv').open(encoding='utf-8') as f:
        return {r['date']: (float(r['net_equity']), float(r['debt']), int(r['positions'])) for r in csv.DictReader(f)}


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

    def maxup(self, code, day, k):
        """其后 k 个交易日内总回报指数的最高点相对当日的涨幅。"""
        if code not in self.s:
            return None
        days, tr = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        if i < 0 or i + k >= len(days):
            return None
        return max(tr[days[j]] for j in range(i + 1, i + k + 1)) / tr[days[i]] - 1

    def day_after(self, code, day, k):
        days, _ = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        return days[min(len(days) - 1, i + k)] if i >= 0 else None

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
    u = EXU.get(arm)
    eps = vals['回撤段']
    return dict(flag=flag, reasons=reasons,
                main=[pm(FULL, arm, W5), pm(EXA, arm, W5), pm(u, arm, W5) if u else None],
                cagr=[pm(FULL, arm, '年化'), pm(EXA, arm, '年化'), pm(u, arm, '年化') if u else None],
                mdd=[pm(FULL, arm, '最大回撤'), pm(EXA, arm, '最大回撤')], dd5=pm(FULL, arm, '滚动5年回撤中位'),
                shallower=sum(ep['delta'] <= -sw.DD_PATH_MDD_GAIN for ep in eps), episodes=len(eps),
                better_starts=sum(FULL[arm][s]['年化'] > FULL[REF][s]['年化'] for s in STARTS),
                clause4=clause4(arm) if u else None)


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


# ── 换仓与集中度账 ───────────────────────────────────────────────────────────────────────────────────────

def held_account(swap):
    """逐起点中位：换仓卖出笔数、其中由已持仓候选触发的占比（swap_account）、门槛臂的已持仓触发次数（stats「换仓触发·持仓不足 T 档」）、
    盈利偏离让位次数。"""
    out = {}
    for arm in ARMS:
        n_held, n_ext = [], []
        for s in STARTS:
            st = json.loads((EXP / 'stats' / f'{tag(arm, s)}.json').read_text())
            n_held.append(sum(v for k, v in st.items() if k.startswith('换仓触发·持仓不足')))
            n_ext.append(st.get('盈利偏离·换仓让位', 0))
        out[arm] = dict(swaps=swap[arm]['swaps_median'], held_share=swap[arm]['held_trigger_share'],
                        held_triggers=med(n_held), ext_trims=med(n_ext))
    return out


def aotewei(nm):
    """奥特维 2026：各臂 2026 年截至末次净值日的净值涨幅（14 起点中位）、2026 年奥特维 contrib（起点平均）、锚点起点成交。"""
    out = {}
    for arm in ARMS:
        ytd, c26 = [], []
        for s in STARTS:
            nav = nav_of(arm, s)
            days = sorted(nav)
            ye = [d for d in days if d <= '2025-12-31'][-1]
            ytd.append(nav[days[-1]][0] / nav[ye][0] - 1)
            det = json.loads((EXP / 'detail' / f'{tag(arm, s)}.json').read_text())
            c26.append(det['contrib_year'].get(f'{AOTEWEI}|2026', 0.0))
        row = dict(ytd_median=med(ytd), ytd_min=min(ytd), ytd_max=max(ytd), contrib2026_mean=sum(c26) / len(c26))
        if arm in CASE_ARMS or arm == REF:
            row['trades'] = [(x['date'], x['action'], x['shares'], x['price'], x['reason'][:30]) for x in ledger_of(arm, ANCHOR)
                             if x['security_code'].zfill(6) == AOTEWEI and '2025-12-01' <= x['date'] <= '2026-03-31']
        out[arm] = row
    return out


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


# ── 执行、陷阱与行为（OI-237 同口径）──────────────────────────────────────────────────────────────────────

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


def swap_account(arms_trades):
    out = {}
    for arm in ARMS:
        n, held_share = [], []
        for s in STARTS:
            spans = defaultdict(list)
            for c in arms_trades[arm][s]:
                spans[c['security_code'].zfill(6)].append((c['entry_date'], c['exit_date']))
            swaps = [x for x in ledger_of(arm, s) if x['action'] == '卖出' and '让位给' in x['reason']]
            n.append(len(swaps))
            held = sum(any(a < x['date'] <= b for a, b in spans.get(x['reason'].split('让位给')[-1].replace('空间更大的', '')[:6], []))
                       for x in swaps)
            held_share.append(held / len(swaps) if swaps else None)
        out[arm] = dict(swaps_median=med(n), held_trigger_share=med(held_share))
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
    last_month = max(r['month'] for r in rows)
    years = {a: year_returns(a) for a in ARMS}
    nm = names()
    res = dict(line=LINE, ref=REF, levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in ARMS if a != REF},
               direct=[pair(a, PARENT[a], years) for a in NEW] + [pair(a, r, years) for a, r in EXTRA_PAIRS],
               years={f'{a}|{r}': year_pair(years[a], years[r]) for a, r in YEAR_PAIRS},
               stock_years={f'{a}|{r}': stock_years(a, r) for a, r in STOCK_YEAR_PAIRS},
               aotewei=aotewei(nm),
               execution=execution(eps, pv, arms_trades, S), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260930)),
               exits=exits(arms_trades), swap_account=swap_account(arms_trades), debt_at_line={a: debt_at_line(a) for a in ARMS},
               stats={},
               strategy={}, cases={})
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
    res['held_account'] = held_account(res['swap_account'])
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, cases, nm)


def write_md(res, cases, nm):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)
    arms = list(ARMS)
    out = [f'# OI-240 读数（v4.221 状态，买入线 {LINE}，14 起点；一档 5%）', '',
           'Δ 均为逐起点配对差中位（pp）。主读数 = 同窗口滚 5 年化配对差；复利读数 = 全期 CAGR 配对差；回撤 Δ 为负 = 更浅。'
           'A = BASE 前五；UC = OI-237 共同剔除集 8 只；U = A ∪ 该臂前五。新臂 CCx = S15 ＋ 已持仓候选的持仓市值未到净资产 x% 才可触发换仓、'
           '卖出款先买触发者一档；CCS15 = 已持仓候选都可触发（不设门槛，也不查 60% 上限）；S15 = 只由未持仓候选触发。读数只作裁定参考。', '',
           '## 一、门槛剂量（上：对 S15；下：对不设门槛的 CCS15）', '',
           '| 臂 | 参照 | 标记 | 主读数 全／A／UC | 复利 全／A／UC | 全期回撤 Δ | 滚5回撤 Δ | 复利胜出起点 | 逐年胜出年数 | 已持仓触发次数（逐起点中位） |',
           '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    ha = res['held_account']
    for p in res['direct']:
        a, r = p['arm'], p['ref']
        out.append(f"| {a} | {r} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | {pp(p['mdd'])} | {pp(p['dd5'])} | "
                   f"{p['better_starts']}/14 | {p['years']['years_pos']}/{p['years']['years']} | {ha[a]['held_triggers']:.0f} |")
    out += ['', '## 二、对 BASE 的叠加读数（U 与第 4 款只对新臂跑）', '',
            '| 臂 | 标记 | 主读数 全／A／U | 复利 全／A／U | 第 4 款 U | 年化 | 最大回撤 | 全期回撤 Δ 全／A | 更浅≥5pp 回撤段 | 复利胜出起点 |',
            '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        if arm == REF:
            out.append(f"| {REF}（参照） | — | — | — | — | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | — | — | — |")
            continue
        r = res['vs_base'][arm]
        c4 = '—'
        if r['clause4']:
            c4 = ('去赢家全面优秀' if r['clause4']['ok'] else '未满足') + ('' if not r['clause4']['bad'] else '（' + '、'.join(
                f"{k} {d * (1 if 'Calmar' in k or 'Sharpe' in k else 100):+.2f}" for k, d in r['clause4']['bad']) + '）')
        out.append(f"| {arm} | {r['flag']} | {trio(r['main'])} | {trio(r['cagr'])} | {c4} | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | "
                   f"{trio(r['mdd'])} | {r['shallower']}/{r['episodes']} | {r['better_starts']}/14 |")
    out += ['', '## 三、换仓与集中度账（14 起点中位）', '',
            '| 臂 | 换仓卖出笔数 | 由已持仓候选触发 | 盈利偏离让位次数 | 涨幅减持 贡献 pp | 持仓只数 | 单票权重中位 | 单票最大 | 前三权重 | 单票超60%天数 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        h, lv, x = ha[arm], res['levels'][arm], res['exits'][arm]
        out.append(f"| {arm} | {h['swaps']:.0f} | {pct(h['held_share'])} | {h['ext_trims']:.0f} | {pp(x['contrib']['涨幅减持'], 1)} | "
                   f"{lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | {pct(lv['单票权重最大'])} | {pct(lv['前三权重中位'])} | {pct(lv['单票超60%天数占比'], 1)} |")
    out += ['', '## 四、奥特维（688516）2026 案例', '',
            '| 臂 | 2026 年至末次净值日 净值涨幅（中位／最低／最高） | 2026 年奥特维 contrib（起点平均，pp） |', '| --- | ---: | ---: |']
    for arm in arms:
        a = res['aotewei'][arm]
        out.append(f"| {arm} | {pct(a['ytd_median'], 1)}／{pct(a['ytd_min'], 1)}／{pct(a['ytd_max'], 1)} | {pp(a['contrib2026_mean'], 1)} |")
    out += ['', '### 锚点起点奥特维成交（2025-12～2026-03）', '']
    for arm in (REF, *CASE_ARMS):
        tr = res['aotewei'][arm].get('trades') or []
        out.append(f"- **{arm}**：" + ('；'.join(f'{d} {act} {q} 股 @{p}（{why}）' for d, act, q, p, why in tr) or '无成交'))
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
    out += ['', '## 六、风险与集中度（14 起点中位；最深回撤、最低担保比例取跨起点极值）', '',
            '| 臂 | 最深回撤 | 滚5最差（最低） | 最低担保比例 | 强平 | 平均仓位 | 换手 | 持仓只数 | 单票权重中位 | 单票最大 | 前三权重 | 单票超60%天数 | 负债到线日 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        out.append(f"| {arm} | {pct(lv['mdd_worst'], 1)} | {pct(lv['worst5_min'], 1)} | {lv['maint_min']:.2f} | {lv['liquidations_max']:.0f} | "
                   f"{pct(lv['平均仓位'])} | {lv['年均换手']:.2f} | {lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | {pct(lv['单票权重最大'])} | "
                   f"{pct(lv['前三权重中位'])} | {pct(lv['单票超60%天数占比'], 1)} | {pct(res['debt_at_line'][arm])} |")
    out += ['', '## 七、执行与陷阱（陷阱 contrib Δ 对 BASE，股票整簇自助 90%）', '',
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
    out += ['', '## 九、第 11 款案例归因（锚点起点 2011-11-01；全表见 case_<臂>_vs_<参照>.md）', '']
    for k, v in res['cases'].items():
        t3 = v['top3']
        out += [f"### {k.replace('|', ' 对 ')}：总差 {pp(t3['total'], 1)}pp，前三只 " + '、'.join(f'{c} {pp(x, 1)}' for c, x in t3['top3'])
                + f"，净额占比 {pct(t3['share'])}", '', '| 公司 | Δ | 归类 | 依据 |', '| --- | ---: | --- | --- |', *v['table'], '']
    out += ['## 十、退出与换仓（14 起点中位）', '',
            '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' | 换仓卖出笔数 | 已持仓触发 |',
            '| --- | ---: | ---: |' + ' ---: |' * (len(EXITS) + 2)]
    for arm in arms:
        x, s = res['exits'][arm], res['swap_account'][arm]
        out.append(f"| {arm} | {x['cycles']} | {x['holding_days_median']} | " + ' | '.join(f"{x['count'][n]:.0f}／{pp(x['contrib'][n], 1)}" for _, n in EXITS)
                   + f" | {s['swaps_median']:.0f} | {pct(s['held_trigger_share'])} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out[:40]))


if __name__ == '__main__':
    main()
