"""OI-247 读数（preregister.md 第 1～8 条）：止损两方案对 S15（现行 BASE）。
参考读数（全样本／A／U，第 4 款 U 表）、分解、长期亏损持仓占款、止损／减仓账、风险与集中度、逐年、具名个案、退出、第 12 款；
另出 OI-246 读数第 4 条（S15 建仓带 v > 0 的周期在各臂下的去向）。

    python3 readings.py     # → readings.json、readings.md
"""
import bisect
import csv
import glob
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
sys.path.insert(0, str(EXP))
import backtest_valuation_strategy as bt  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
import sweep_backtest_configs as sw  # noqa: E402
from moat_param_lab import total_return_index  # noqa: E402
from run import A_SET, ARMS, LT, NEW, REF, SA, STATES  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
SA_ARMS = ['SA20L', 'SA60L', 'SA20C', 'SA60C', 'SP20L']
LT_ARMS = [a for a in ARMS if a.startswith('LT')]
PAIRS = [('SA20L', 'SP20L'), ('SA60L', 'SA20L'), ('SA20C', 'SA20L'), ('SA60C', 'SA60L')]
YEAR_ARMS = SA_ARMS + ['LT63K10', 'LT126K10', 'LT189K10', 'LT252K10']
EXITS = (('止损', '止损'), ('水下', '水下减仓'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'),
         ('强平', '强平'), ('回测截止', '截止清算'))
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
CREDIT = 0.666
FAMILY_BEFORE = 109           # OI-233～OI-242 已试臂数（OI-242 止）
CASE_CODE, CASE_FROM = '600970', '2024-05-01'
UW = (126, 252)


def load(path):
    sw.set_market(sw.scan_market(path))
    groups, _orders, failed, *_ = sw.load_scan(path)
    assert not any(failed.values()), (path, failed)
    return groups


FULL = load(EXP / 'sweep_full.txt')['']
EXA = load(EXP / 'sweep_A.txt')[sw.EX5_PREFIX]
EXU = {a: load(EXP / 'u' / f'{a}.txt')[sw.EX5_PREFIX] for a in NEW}


def pm(grp, arm, key, ref=REF):
    return sw._paired_median(grp, arm, key, ref=ref)


def med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def tag(arm, start):
    return sw.summary_tag(arm + 'full', start, '')


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


def stats_of(arm, start):
    return json.loads((EXP / 'stats' / f'{tag(arm, start)}.json').read_text(encoding='utf-8'))


def names():
    out = {}
    for p in glob.glob(str(EXP / 'ledgers' / 'ledger_*.csv')):
        for r in csv.DictReader(open(p, encoding='utf-8')):
            if r.get('security_name'):
                out.setdefault(r['security_code'].zfill(6), r['security_name'])
    for path in (ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv', ROOT / 'data/raw/a_share_securities.csv'):
        if path.exists():
            for r in csv.DictReader(path.open(encoding='utf-8-sig')):
                if r.get('security_code') and r.get('security_name'):
                    out.setdefault(r['security_code'].zfill(6), r['security_name'])
    return out


class TR:
    """含分红再投总回报指数（与 OI-242 同源），按交易日查询与前移。"""

    def __init__(self, codes):
        bhv.ACTIONS = bt.ACTIONS
        actions = bhv.load_actions()
        self.s = {}
        for code in codes:
            prices = bhv.load_ohlcv(code)
            if prices:
                days = [d for d, _ in prices]
                self.s[code] = (days, total_return_index(prices, actions.get(code, [])))

    def fwd(self, code, day, n):
        if code not in self.s:
            return None
        days, tr = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        if i < 0 or i + n >= len(days):
            return None
        return tr[days[i + n]] / tr[days[i]] - 1

    def within(self, code, a, n):
        """a 之后第 n 个交易日（含）的日期。"""
        if code not in self.s:
            return None
        days, _ = self.s[code]
        i = bisect.bisect_right(days, a) - 1
        return days[min(len(days) - 1, i + n)] if i >= 0 else None

    def prev(self, code, day):
        if code not in self.s:
            return None
        days, _ = self.s[code]
        i = bisect.bisect_left(days, day) - 1
        return days[i] if i >= 0 else None


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


def pair(arm, ref):
    flag, reasons, _ = sw.reading_flags(FULL, EXA, arm, ref=ref)
    return dict(arm=arm, ref=ref, flag=flag, reasons=reasons, main=[pm(FULL, arm, W5, ref), pm(EXA, arm, W5, ref)],
                cagr=[pm(FULL, arm, '年化', ref), pm(EXA, arm, '年化', ref)], mdd=pm(FULL, arm, '最大回撤', ref),
                dd5=pm(FULL, arm, '滚动5年回撤中位', ref), better_starts=sum(FULL[arm][s]['年化'] > FULL[ref][s]['年化'] for s in STARTS))


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


def debt_at_line(arm):
    return med([sum(debt >= CREDIT * e - 1 for e, debt, _ in nav.values() if e > 0) / len(nav) for nav in (nav_of(arm, s) for s in STARTS)])


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


# ── 读数第 3 条：长期亏损持仓占款（逐日持仓）────────────────────────────────────────────────────────────

def occupancy(arm, closes):
    per = []
    for s in STARTS:
        streak, cycle_max, occ, days, max_streak, long_cycles = {}, {}, {n: 0.0 for n in UW}, 0, 0, 0
        rows = defaultdict(list)
        with gzip.open(EXP / 'snaps' / f'{tag(arm, s)}.csv.gz', 'rt', newline='') as f:
            for r in csv.DictReader(f):
                rows[r['date']].append(r)
        nav = nav_of(arm, s)
        for d in sorted(nav):                                # 分母取全部净值日（含空仓日）
            held = {r['code']: r for r in rows.get(d, [])}
            for c in list(streak):
                if c not in held:                           # 周期结束
                    long_cycles += cycle_max.pop(c, 0) >= 252
                    streak.pop(c)
            eq = nav[d][0]
            wsum = {n: 0.0 for n in UW}
            for c, r in held.items():
                px = closes.get(c, {}).get(d)
                shares, cost = float(r['shares']), float(r['cost'])
                if px is not None and cost > 0:
                    streak[c] = streak.get(c, 0) + 1 if px < cost else 0
                else:
                    streak.setdefault(c, 0)
                cycle_max[c] = max(cycle_max.get(c, 0), streak[c])
                max_streak = max(max_streak, streak[c])
                if px is not None and eq > 0:
                    for n in UW:
                        if streak[c] >= n:
                            wsum[n] += shares * px / eq
            for n in UW:
                occ[n] += wsum[n]
            days += 1
        long_cycles += sum(v >= 252 for v in cycle_max.values())
        per.append(dict(occ={n: occ[n] / days for n in UW} if days else None, max_streak=max_streak, long_cycles=long_cycles))
    return dict(occ={n: med([p['occ'][n] for p in per if p['occ']]) for n in UW}, max_streak=med([p['max_streak'] for p in per]),
                long_cycles=med([p['long_cycles'] for p in per]))


# ── 读数第 4 条：止损／减仓账 ─────────────────────────────────────────────────────────────────────────────

def release_lag(arm):
    """解除距建仓的交易日数（逐日持仓里止损锚由正变 0 的间隔），14 起点合并取中位。"""
    lags = []
    for s in STARTS:
        seqs = defaultdict(list)
        with gzip.open(EXP / 'snaps' / f'{tag(arm, s)}.csv.gz', 'rt', newline='') as f:
            for r in csv.DictReader(f):
                seqs[r['code']].append((r['date'], float(r['stop'])))
        for seq in seqs.values():
            seq.sort()
            prev, start = None, None
            for i, (_, sv) in enumerate(seq):
                if (prev is None or prev == 0) and sv > 0:
                    start = i
                elif prev and sv == 0 and start is not None:
                    lags.append(i - start)
                    start = None
                prev = sv
    return med(lags)


def stop_ledger(arm, arms_trades, T):
    stops, per_path, rel, cyc, ent = {}, [], [], [], []
    for s, cycles in arms_trades[arm].items():
        n = 0
        by_code = defaultdict(list)
        for x in cycles:
            by_code[x['security_code'].zfill(6)].append(x)
        for x in cycles:
            if '止损' not in x['exit_reason']:
                continue
            n += 1
            code, day = x['security_code'].zfill(6), x['exit_date']
            horizon = T.within(code, day, 60)
            rebuy = any(day < y['entry_date'] <= horizon for y in by_code[code]) if horizon else None
            stops.setdefault((code, day), dict(days=int(x['holding_days'] or 0), ret=float(x['return_pct'] or 0),
                                                f60=T.fwd(code, day, 60), f250=T.fwd(code, day, 250), rebuy=rebuy))
        per_path.append(n)
        st = stats_of(arm, s)
        rel.append(st.get('前低止损·走强解除', 0))
        cyc.append(len(cycles))
        ent.append(st.get('前低建仓', 0) + st.get('前低建仓·无锚沿用MA60', 0))   # 新建仓数（闭合周期不含截止日无行情的持仓）
    v = list(stops.values())
    return dict(stops_path=med(per_path), cycles_path=med(cyc), entries_path=med(ent),
                stop_share=med([a / b for a, b in zip(per_path, ent) if b]),
                release_share=med([a / b for a, b in zip(rel, ent) if b]), release_lag=release_lag(arm), unique=len(v),
                days_median=med([x['days'] for x in v]), ret_median=med([x['ret'] for x in v]),
                f60_median=med([x['f60'] for x in v]), f60_pos=_share([x['f60'] for x in v], lambda z: z > 0),
                f250_median=med([x['f250'] for x in v]), f250_pos=_share([x['f250'] for x in v], lambda z: z > 0),
                rebuy60=_share([x['rebuy'] for x in v], lambda z: z))


def _share(xs, cond):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if cond(x)) / len(xs) if xs else None


def trim_ledger(arm, T, closes):
    events, per_path = {}, []
    for s in STARTS:
        nav = nav_of(arm, s)
        cost_at = {}
        with gzip.open(EXP / 'snaps' / f'{tag(arm, s)}.csv.gz', 'rt', newline='') as f:
            prev = {}
            for r in csv.DictReader(f):
                prev[(r['date'], r['code'])] = float(r['cost'])
            cost_at = prev
        n = 0
        for x in ledger_of(arm, s):
            if x['action'] != '卖出' or '水下' not in x['reason']:
                continue
            n += 1
            code, day = x['security_code'].zfill(6), x['date']
            eq = nav.get(day, (None,))[0]
            pday = T.prev(code, day)
            cost = cost_at.get((pday, code)) if pday else None
            rec = None
            base_px = closes.get(code, {}).get(pday) if pday else None
            if cost and base_px and code in T.s:            # 按含权总回报指数把其后价格折回信号日口径，再比持仓均价
                days, tr = T.s[code]
                i = bisect.bisect_right(days, pday) - 1
                seg = days[i + 1:i + 1 + 250] if i >= 0 else []
                rec = any(base_px * tr[d] / tr[days[i]] >= cost for d in seg) if seg else None
            events.setdefault((code, day), dict(amount=float(x['amount']) / eq if eq else None, f60=T.fwd(code, day, 60),
                                                f250=T.fwd(code, day, 250), recovered=rec, full='清仓' in x['reason']))
        per_path.append(n)
    v = list(events.values())
    return dict(trims_path=med(per_path), unique=len(v), amount_median=med([x['amount'] for x in v]),
                full_share=_share([x['full'] for x in v], lambda z: z), f60_median=med([x['f60'] for x in v]),
                f60_pos=_share([x['f60'] for x in v], lambda z: z > 0), f250_median=med([x['f250'] for x in v]),
                f250_pos=_share([x['f250'] for x in v], lambda z: z > 0), recovered=_share([x['recovered'] for x in v], lambda z: z))


# ── 读数第 7 条：具名个案与谷底守卫周期（OI-246 读数第 4 条）─────────────────────────────────────────────────

def case_cycles(arms_trades):
    out = {}
    for arm, starts in arms_trades.items():
        out[arm] = [dict(entry=x['entry_date'], exit=x['exit_date'], reason=x['exit_reason'], contrib=float(x['contrib'] or 0))
                    for x in starts[ANCHOR] if x['security_code'].zfill(6) == CASE_CODE and x['exit_date'] >= CASE_FROM]
    return out


def trough_cycles(arms_trades, T):
    ref = [(s, x) for s, cycles in arms_trades[REF].items() for x in cycles]
    need = {}
    for s, x in ref:
        code = x['security_code'].zfill(6)
        sig = T.prev(code, x['entry_date'])
        if sig:
            need[(code, sig)] = None
    with (STATES / 'a_share_daily_states_adopted.csv').open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, irp, iav = (h.index(k) for k in ('security_code', 'date', 'band_report_date', 'band_available_at'))
        codes = {c for c, _ in need}
        for row in reader:
            if row[ic] in codes and (row[ic], row[idt]) in need:
                need[(row[ic], row[idt])] = (row[irp], row[iav])
    tw = {}
    with (ROOT / 'data/processed/roic_bands.csv').open(newline='', encoding='utf-8') as f:
        keys = {v for v in need.values() if v}
        for r in csv.DictReader(f):
            k = (r['report_date'], r['available_at'])
            if k in keys:
                tw[(r['security_code'], *k)] = float(r['trough_weight'] or 0)
    rows = []
    for s, x in ref:
        code = x['security_code'].zfill(6)
        key = need.get((code, T.prev(code, x['entry_date']) or ''))
        v = tw.get((code, *key)) if key else None
        if v and v > 0:
            rows.append((s, x, v))
    summary = {}
    for arm, starts in arms_trades.items():
        found, stopped, trimmed, c_arm, c_ref = 0, 0, 0, 0.0, 0.0
        trim_days = {}
        if arm in LT_ARMS:
            for s in STARTS:
                for z in ledger_of(arm, s):
                    if z['action'] == '卖出' and '水下' in z['reason']:
                        trim_days.setdefault((s, z['security_code'].zfill(6)), []).append(z['date'])
        for s, x, _v in rows:
            y = next((y for y in starts[s] if y['security_code'] == x['security_code'] and y['entry_date'] == x['entry_date']), None)
            if y is None:
                continue
            found += 1
            stopped += '止损' in y['exit_reason']
            trimmed += any(y['entry_date'] <= d <= y['exit_date'] for d in trim_days.get((s, y['security_code'].zfill(6)), ()))
            c_arm += float(y['contrib'] or 0)
            c_ref += float(x['contrib'] or 0)                  # 同一批（同日建仓）周期的 S15 贡献
        summary[arm] = dict(cycles=len(rows), matched=found, stopped=stopped, trimmed=trimmed, contrib_arm=c_arm, contrib_ref=c_ref)
    all_ref = [x for _s, x in ref]
    by_v = {}
    for name, lo, hi in (('v ≥ 0.5', 0.5, 9.0), ('0 < v < 0.5', 1e-12, 0.5)):
        sel = [x for _s, x, v in rows if lo <= v < hi]
        by_v[name] = dict(cycles=len(sel), contrib=sum(float(x['contrib'] or 0) for x in sel),
                          win=_share([float(x['return_pct'] or 0) for x in sel], lambda z: z > 0))
    ref_total = dict(cycles=len(all_ref), contrib=sum(float(x['contrib'] or 0) for x in all_ref),
                     win=_share([float(x['return_pct'] or 0) for x in all_ref], lambda z: z > 0))
    detail = sorted(({'start': s, 'code': x['security_code'].zfill(6), 'entry': x['entry_date'], 'exit': x['exit_date'], 'v': v,
                      'reason': x['exit_reason'], 'contrib': float(x['contrib'] or 0)} for s, x, v in rows if s == ANCHOR),
                    key=lambda r: r['entry'])
    return dict(summary=summary, by_v=by_v, ref_total=ref_total, anchor_detail=detail)


def main():
    arms_trades = {a: trades_of(a) for a in ARMS}
    codes = {c['security_code'].zfill(6) for st in arms_trades.values() for cs in st.values() for c in cs}
    T = TR(codes)
    closes = bt.load_prices(codes)
    nm = names()
    years = {a: year_returns(a) for a in [REF] + YEAR_ARMS}
    res = dict(ref=REF, A=A_SET, levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in NEW},
               pairs=[pair(a, r) for a, r in PAIRS], years={f'{a}|{REF}': year_pair(years[a], years[REF]) for a in YEAR_ARMS},
               exits=exits(arms_trades), debt_at_line={a: debt_at_line(a) for a in ARMS},
               occupancy={a: occupancy(a, closes) for a in ARMS},
               stops={a: stop_ledger(a, arms_trades, T) for a in SA_ARMS},
               trims={a: trim_ledger(a, T, closes) for a in LT_ARMS},
               case=case_cycles(arms_trades), trough=trough_cycles(arms_trades, T),
               stats_keys={a: {k: med([stats_of(a, s).get(k, 0) for s in STARTS]) for k in
                               ('前低建仓', '前低建仓·无锚沿用MA60', '前低建仓·无锚不设止损', '前低止损·走强解除', '水下减仓·减仓', '水下减仓·清仓',
                                '水下满期·已在上限内')} for a in ARMS},
               family=dict(before=FAMILY_BEFORE, new=len(NEW), total=FAMILY_BEFORE + len(NEW)))
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, nm)


def write_md(res, nm):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)
    rule = lambda a: (f"前低 {SA[a][0]} 日·{'全天最低' if SA[a][1] == 'low' else '收盘最低'}·走强解除" if a in SA else
                      '前低 20 日·全天最低·不解除' if a == 'SP20L' else f"水下 {LT[a][0]} 日·减至 {LT[a][1]:.0%}" if a in LT else '现行')
    out = ['# OI-247 读数（v4.225 状态，买入线 1.0034，14 起点；参照 S15 = 现行 BASE，不设价格止损）', '',
           'Δ 均为逐起点配对差中位（pp）。主读数 = 同窗口滚 5 年化配对差；复利读数 = 全期 CAGR 配对差；回撤 Δ 为负 = 更浅。'
           f"A = S15 锚点前五（{'、'.join(nm.get(c, c) for c in A_SET)}）；U = A ∪ 该臂前五。读数只作裁定参考。", '',
           '## 一、对 S15 的参考读数', '',
           '| 臂 | 规则 | 标记 | 主读数 全／A／U | 复利 全／A／U | 第 4 款 U | 年化 | 最大回撤 | 全期回撤 Δ 全／A | 滚5回撤 Δ | 更浅≥5pp 回撤段 | 复利胜出起点 |',
           '| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        lv = res['levels'][arm]
        if arm == REF:
            out.append(f"| {REF}（参照） | 现行 | — | — | — | — | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | — | — | — | — |")
            continue
        r = res['vs_base'][arm]
        c4 = ('去赢家全面优秀' if r['clause4']['ok'] else '未满足') + ('' if not r['clause4']['bad'] else '（' + '、'.join(
            f"{k} {d * (1 if 'Calmar' in k or 'Sharpe' in k else 100):+.2f}" for k, d in r['clause4']['bad']) + '）')
        out.append(f"| {arm} | {rule(arm)} | {r['flag']} | {trio(r['main'])} | {trio(r['cagr'])} | {c4} | {pct(lv['年化'], 1)} | "
                   f"{pct(lv['最大回撤'], 1)} | {trio(r['mdd'])} | {pp(r['dd5'])} | {r['shallower']}/{r['episodes']} | {r['better_starts']}/14 |")
    out += ['', '### 标记依据', '']
    for arm in NEW:
        out.append(f"- **{arm}**：{res['vs_base'][arm]['flag']}；" + ('；'.join(res['vs_base'][arm]['reasons']) or '—'))
    out += ['', '### 方案二主读数（全样本）网格：行 = 水下天数，列 = 留仓比例', '', '| 水下天数 | 5% | 10% | 15% |', '| ---: | ---: | ---: | ---: |']
    for m in (63, 126, 189, 252):
        out.append(f'| {m} | ' + ' | '.join(pp(res['vs_base'][f'LT{m}K{x}']['main'][0]) for x in (5, 10, 15)) + ' |')
    out += ['', '## 二、分解（全样本／A）', '', '| 对比 | 标记 | 主读数 全／A | 复利 全／A | 全期回撤 Δ | 滚5回撤 Δ | 复利胜出起点 |',
            '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for p in res['pairs']:
        out.append(f"| {p['arm']} 对 {p['ref']} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | {pp(p['mdd'])} | {pp(p['dd5'])} | "
                   f"{p['better_starts']}/14 |")
    out += ['', '## 三、长期亏损持仓占款（14 起点中位）', '',
            '| 臂 | 规则 | 水下 ≥126 日持仓占净资产（时间平均） | 水下 ≥252 日 | 最长水下天数 | 最长水下段 ≥252 日的周期数 |',
            '| --- | --- | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        o = res['occupancy'][arm]
        out.append(f"| {arm} | {rule(arm)} | {pct(o['occ'][126], 1)} | {pct(o['occ'][252], 1)} | {o['max_streak']:.0f} | {o['long_cycles']:.0f} |")
    out += ['', '## 四、止损／减仓账（全样本；逐笔按（代码, 日期）跨起点去重）', '', '### 方案一',
            '', '| 臂 | 止损笔数／路径 | 新建仓／路径 | 周期数／路径 | 新建仓被止损占比 | 走强解除占比 | 解除距建仓（交易日，中位） | 去重笔数 | 持有天数中位 | 止损时周期回报中位 | 其后 60 日回报 中位／为正 | 其后 250 日 中位／为正 | 60 日内买回 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in SA_ARMS:
        s = res['stops'][arm]
        out.append(f"| {arm} | {s['stops_path']} | {s['entries_path']} | {s['cycles_path']} | {pct(s['stop_share'])} | {pct(s['release_share'])} | {s['release_lag'] if s['release_lag'] is not None else '—'} | {s['unique']} | "
                   f"{s['days_median']} | {pct(s['ret_median'], 1)} | {pct(s['f60_median'], 1)}／{pct(s['f60_pos'])} | "
                   f"{pct(s['f250_median'], 1)}／{pct(s['f250_pos'])} | {pct(s['rebuy60'])} |")
    out += ['', '占比以新建仓数（引擎计数）为分母；周期数只含闭合周期，回测末日无行情的持仓不清算、不计入。解除距建仓按逐日持仓里止损锚由正变 0 的间隔计（未预登记，描述用）。']
    out += ['', '### 方案二', '', '| 臂 | 减仓笔数／路径 | 去重笔数 | 金额占净资产中位 | 其中清仓 | 其后 60 日回报 中位／为正 | 其后 250 日 中位／为正 | 250 日内回本 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in LT_ARMS:
        t = res['trims'][arm]
        out.append(f"| {arm} | {t['trims_path']} | {t['unique']} | {pct(t['amount_median'], 1)} | {pct(t['full_share'])} | "
                   f"{pct(t['f60_median'], 1)}／{pct(t['f60_pos'])} | {pct(t['f250_median'], 1)}／{pct(t['f250_pos'])} | {pct(t['recovered'])} |")
    out += ['', '## 五、风险与集中度（14 起点中位；最深回撤、最低担保比例、滚5最差取跨起点极值）', '',
            '| 臂 | 最深回撤 | 滚5最差（最低） | 最低担保比例 | 强平 | 平均仓位 | 换手 | 持仓只数 | 单票权重中位 | 单票最大 | 前三权重 | 负债到线日 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        lv = res['levels'][arm]
        out.append(f"| {arm} | {pct(lv['mdd_worst'], 1)} | {pct(lv['worst5_min'], 1)} | {lv['maint_min']:.2f} | {lv['liquidations_max']:.0f} | "
                   f"{pct(lv['平均仓位'])} | {lv['年均换手']:.2f} | {lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | {pct(lv['单票权重最大'])} | "
                   f"{pct(lv['前三权重中位'])} | {pct(res['debt_at_line'][arm])} |")
    out += ['', '## 六、逐年配对差（对 S15；整年在场的起点，中位 pp；括号内为胜出起点数／起点数）', '']
    yrs = sorted({int(y) for v in res['years'].values() for y in v['per_year']})
    out += ['| 对比 | ' + ' | '.join(str(y) for y in yrs) + ' | 胜出年数 |', '| --- |' + ' ---: |' * (len(yrs) + 1)]
    for k, v in res['years'].items():
        cells = [f"{pp(v['per_year'][y]['median'], 1)}（{v['per_year'][y]['better']}/{v['per_year'][y]['n']}）" if y in v['per_year'] else '—' for y in yrs]
        out.append(f"| {k.replace('|', ' 对 ')} | " + ' | '.join(cells) + f" | {v['years_pos']}/{v['years']} |")
    out += ['', f'## 七、具名个案（锚点起点 {ANCHOR}）', '', f'### 中材国际（{CASE_FROM} 起的周期）', '', '| 臂 | 周期（建仓→清仓，退出方式，contrib pp） |', '| --- | --- |']
    for arm in ARMS:
        cs = res['case'][arm]
        out.append(f"| {arm} | " + ('；'.join(f"{c['entry']}→{c['exit']}，{c['reason']}，{pp(c['contrib'], 1)}" for c in cs) or '未持有') + ' |')
    tr = res['trough']
    out += ['', '### 建仓带谷底守卫 v > 0 的周期（S15 全样本 14 起点；OI-246 读数第 4 条）', '',
            f"S15 全部闭合周期 {tr['ref_total']['cycles']} 个，contrib 合计 {pp(tr['ref_total']['contrib'], 1)}pp，周期回报为正 {pct(tr['ref_total']['win'])}（14 起点加总）。其中建仓带 v > 0：", '',
            '| 分组 | 周期数 | contrib 合计 pp | 周期回报为正 |', '| --- | ---: | ---: | ---: |']
    for name, b in tr['by_v'].items():
        out.append(f"| {name} | {b['cycles']} | {pp(b['contrib'], 1)} | {pct(b['win'])} |")
    out += ['', '各臂下同一周期（同代码、同日建仓）的去向；路径分叉后建仓日不同的周期不计入配对：', '',
            '| 臂 | 同日建仓的周期 | 其中止损退出 | 其中有水下减仓 | contrib 合计（臂） | 同批周期 S15 合计 |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        s = tr['summary'][arm]
        out.append(f"| {arm} | {s['matched']}/{s['cycles']} | {s['stopped']} | {s['trimmed']} | {pp(s['contrib_arm'], 1)} | {pp(s['contrib_ref'], 1)} |")
    out += ['', f'锚点起点明细：', '', '| 代码 | 名称 | 建仓 | 清仓 | v | 退出 | contrib pp |', '| --- | --- | --- | --- | ---: | --- | ---: |']
    for r in tr['anchor_detail']:
        out.append(f"| {r['code']} | {nm.get(r['code'], '')} | {r['entry']} | {r['exit']} | {r['v']:.2f} | {r['reason']} | {pp(r['contrib'], 1)} |")
    out += ['', '## 八、退出（14 起点中位：周期数／contrib pp）', '', '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' |',
            '| --- | ---: | ---: |' + ' ---: |' * len(EXITS)]
    for arm in ARMS:
        x = res['exits'][arm]
        out.append(f"| {arm} | {x['cycles']} | {x['holding_days_median']} | " + ' | '.join(f"{x['count'][n]:.0f}／{pp(x['contrib'][n], 1)}" for _, n in EXITS) + ' |')
    out += ['', '引擎计数（14 起点中位）：' + '；'.join(f"{a} " + '、'.join(f'{k} {v:.0f}' for k, v in res['stats_keys'][a].items() if v)
                                           for a in ARMS if any(res['stats_keys'][a].values())), '']
    f = res['family']
    out += [f"## 九、第 12 款：本族（OI-233 起的执行层研究）已试 {f['before']} 臂，本批新增 {f['new']} 臂，合计 {f['total']} 臂。", '']
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out[:40]))


if __name__ == '__main__':
    main()
