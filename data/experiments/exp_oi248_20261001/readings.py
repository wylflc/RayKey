"""OI-248 读数（preregister.md 第 1～10 条）：加仓后回落——只给盈利仓加仓（AG）与回落撤回加仓（AB／ABM／AX）对 S15（现行 BASE）。
参考读数（全样本／A／U，第 4 款 U 表）、分解、本题目标（加仓过且水下的占款）、撤回账、加仓闸账、中材国际、风险与集中度、逐年、退出、第 12 款。

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
from run import A_SET, AB, AG, ARMS, NEW, REF  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
AG_ARMS = list(AG)
AB_ARMS = list(AB) + ['AX10']
PAIRS = [('AG0', 'AGm5'), ('AG5', 'AG0'), ('AB5', 'AB0'), ('AB10', 'AB5'), ('ABM5', 'ABM0'), ('ABM10', 'ABM5'),
         ('ABM0', 'AB0'), ('ABM5', 'AB5'), ('ABM10', 'AB10'), ('AX10', 'AB10')]
YEAR_ARMS = list(NEW)
EXITS = (('加仓后回落', '加仓后回落'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'),
         ('强平', '强平'), ('回测截止', '截止清算'))
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
CREDIT = 0.666
FAMILY_BEFORE = 131           # OI-233～OI-247 的 126 臂加 OI-246 第二段 5 臂
GAP = 20
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


def _share(xs, cond):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if cond(x)) / len(xs) if xs else None


def gap(T, code, a, b):
    days = T.s[code][0] if code in T.s else None
    if not days:
        return GAP + 1
    return bisect.bisect_right(days, b) - bisect.bisect_right(days, a)


# ── 读数第 3 条：加仓过且水下的占款（逐日持仓）───────────────────────────────────────────────────────────

def added_underwater(arm, closes):
    per = []
    for s in STARTS:
        rows = defaultdict(list)
        with gzip.open(EXP / 'snaps' / f'{tag(arm, s)}.csv.gz', 'rt', newline='') as f:
            for r in csv.DictReader(f):
                rows[r['date']].append(r)
        nav = nav_of(arm, s)
        tot0, tot9, days = 0.0, 0.0, 0
        for d in sorted(nav):
            eq = nav[d][0]
            w0 = w9 = 0.0
            for r in rows.get(d, []):
                if int(r['buys']) < 2:
                    continue
                px = closes.get(r['code'], {}).get(d)
                cost = float(r['cost'])
                if px is None or cost <= 0 or eq <= 0:
                    continue
                mv = float(r['shares']) * px / eq
                if px < cost:
                    w0 += mv
                if px < cost * 0.9:
                    w9 += mv
            tot0 += w0
            tot9 += w9
            days += 1
        per.append((tot0 / days, tot9 / days) if days else (None, None))
    return dict(uw=med([p[0] for p in per]), uw10=med([p[1] for p in per]))


# ── 读数第 4 条：撤回账 ──────────────────────────────────────────────────────────────────────────────

def cut_ledger(arm, arms_trades, T, closes):
    per_path, events, readd = [], {}, []
    for s in STARTS:
        with (EXP / 'events' / f'{tag(arm, s)}_ab.csv').open(newline='', encoding='utf-8') as f:
            cuts = list(csv.DictReader(f))
        per_path.append(len(cuts))
        nav = nav_of(arm, s)
        led = ledger_of(arm, s)
        buys = defaultdict(list)
        for z in led:
            if z['action'] == '买入':
                buys[z['security_code'].zfill(6)].append(z['date'])
        cycles = defaultdict(list)
        for x in arms_trades[arm][s]:
            cycles[x['security_code'].zfill(6)].append((x['entry_date'], x['exit_date']))
        for c in cuts:
            code, day = c['code'].zfill(6), c['day']
            eq = nav.get(day, (None,))[0]
            cost = float(c['avg_cost'])
            base_px = closes.get(code, {}).get(day)
            rec = None
            if base_px and code in T.s:
                days, tr = T.s[code]
                i = bisect.bisect_right(days, day) - 1
                seg = days[i + 1:i + 1 + 250] if i >= 0 else []
                rec = any(base_px * tr[d] / tr[days[i]] >= cost for d in seg) if seg else None
            events.setdefault((code, day), dict(amount=float(c['sold']) / eq if eq else None, full=c['full'] == '1',
                                                f60=T.fwd(code, day, 60), f250=T.fwd(code, day, 250), recovered=rec))
            if c['full'] != '1':
                end = next((b for a, b in cycles[code] if a <= day <= b), '9999-12-31')
                readd.append(any(day < b <= end for b in buys[code]))
    v = list(events.values())
    return dict(cuts_path=med(per_path), unique=len(v), amount_median=med([x['amount'] for x in v]),
                full_share=_share([x['full'] for x in v], lambda z: z),
                f60_median=med([x['f60'] for x in v]), f60_pos=_share([x['f60'] for x in v], lambda z: z > 0),
                f250_median=med([x['f250'] for x in v]), f250_pos=_share([x['f250'] for x in v], lambda z: z > 0),
                recovered=_share([x['recovered'] for x in v], lambda z: z), readd=_share(readd, lambda z: z))


# ── 读数第 5 条：加仓闸账 ────────────────────────────────────────────────────────────────────────────

def ref_adds(T):
    """S15 实际加仓（跨起点按（代码, 信号日）去重）。"""
    out = set()
    for s in STARTS:
        for z in ledger_of(REF, s):
            if z['action'] == '买入' and z['reason'] == '定投加仓':
                code = z['security_code'].zfill(6)
                sig = T.prev(code, z['date'])
                if sig:
                    out.add((code, sig))
    f60 = [T.fwd(c, d, 60) for c, d in out]
    f250 = [T.fwd(c, d, 250) for c, d in out]
    return dict(adds=len(out), f60_median=med(f60), f60_pos=_share(f60, lambda z: z > 0),
                f250_median=med(f250), f250_pos=_share(f250, lambda z: z > 0))


def gate_ledger(arm, T):
    per_days, per_events, union = [], [], defaultdict(set)
    for s in STARTS:
        with (EXP / 'events' / f'{tag(arm, s)}_ag.csv').open(newline='', encoding='utf-8') as f:
            rows = [(r['code'].zfill(6), r['signal_day']) for r in csv.DictReader(f)]
        per_days.append(len(rows))
        last, n = {}, 0
        for code, d in sorted(rows):
            if code not in last or gap(T, code, last[code], d) > GAP:
                n += 1
            last[code] = d
            union[code].add(d)
        per_events.append(n)
    events = []
    for code, days in union.items():
        prev = None
        for d in sorted(days):
            if prev is None or gap(T, code, prev, d) > GAP:
                events.append((code, d))
            prev = d
    f60 = [T.fwd(c, d, 60) for c, d in events]
    f250 = [T.fwd(c, d, 250) for c, d in events]
    return dict(days_path=med(per_days), events_path=med(per_events), events=len(events), codes=len(union),
                f60_median=med(f60), f60_pos=_share(f60, lambda z: z > 0), f250_median=med(f250), f250_pos=_share(f250, lambda z: z > 0))


# ── 读数第 6 条：中材国际 ────────────────────────────────────────────────────────────────────────────

def case_cycles(arms_trades):
    out = {}
    for arm, starts in arms_trades.items():
        out[arm] = [dict(entry=x['entry_date'], exit=x['exit_date'], reason=x['exit_reason'], contrib=float(x['contrib'] or 0))
                    for x in starts[ANCHOR] if x['security_code'].zfill(6) == CASE_CODE and x['exit_date'] >= CASE_FROM]
    return out


def case_trades(arm):
    return [(z['date'], z['action'], z['shares'], z['price'], z['reason']) for z in ledger_of(arm, ANCHOR)
            if z['security_code'].zfill(6) == CASE_CODE and z['date'] >= CASE_FROM and z['reason'] not in ('定投加仓',)]


def main():
    arms_trades = {a: trades_of(a) for a in ARMS}
    codes = {c['security_code'].zfill(6) for st in arms_trades.values() for cs in st.values() for c in cs}
    for a in NEW:
        for s in STARTS:
            for suffix in ('ag', 'ab'):
                with (EXP / 'events' / f'{tag(a, s)}_{suffix}.csv').open(newline='', encoding='utf-8') as f:
                    codes |= {r['code'].zfill(6) for r in csv.DictReader(f)}
    T = TR(codes)
    closes = bt.load_prices(codes)
    nm = names()
    years = {a: year_returns(a) for a in [REF] + YEAR_ARMS}
    res = dict(ref=REF, A=A_SET, levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in NEW},
               pairs=[pair(a, r) for a, r in PAIRS], years={f'{a}|{REF}': year_pair(years[a], years[REF]) for a in YEAR_ARMS},
               exits=exits(arms_trades), debt_at_line={a: debt_at_line(a) for a in ARMS},
               added_uw={a: added_underwater(a, closes) for a in ARMS}, occupancy={a: occupancy(a, closes) for a in ARMS},
               cuts={a: cut_ledger(a, arms_trades, T, closes) for a in AB_ARMS},
               gates={a: gate_ledger(a, T) for a in AG_ARMS}, ref_adds=ref_adds(T),
               case=case_cycles(arms_trades), case_trades={a: case_trades(a) for a in ARMS},
               stats_keys={a: {k: med([stats_of(a, s).get(k, 0) for s in STARTS]) for k in
                               ('加仓闸·挡下', '撤回加仓·减仓', '撤回加仓·清仓', '撤回加仓·解锁', '撤回加仓·锁定中不加')} for a in ARMS},
               family=dict(before=FAMILY_BEFORE, new=len(NEW), total=FAMILY_BEFORE + len(NEW)))
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, nm)


def write_md(res, nm):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)

    def rule(a):
        if a == REF:
            return '现行'
        if a in AG:
            return f"加仓须收盘 > 均价 × {1 + AG[a]:.2f}"
        if a == 'AX10':
            return '加仓后收盘 < 均价 × 0.90 清仓'
        d, ma = AB[a]
        return f"加仓后收盘 < 均价 × {1 - d:.2f}" + ('且 MA20 ≤ MA60' if ma else '') + '，撤回到一档'
    out = ['# OI-248 读数（v4.225 状态，买入线 1.0034，14 起点；参照 S15 = 现行 BASE）', '',
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
    out += ['', '### 规则二主读数（全样本）网格：行 = 跌破均价幅度，列 = 是否另须 MA20 ≤ MA60', '', '| d | 不看均线 | MA20 ≤ MA60 |', '| ---: | ---: | ---: |']
    for d in (0, 5, 10):
        out.append(f"| {d}% | {pp(res['vs_base'][f'AB{d}']['main'][0])} | {pp(res['vs_base'][f'ABM{d}']['main'][0])} |")
    out += ['', '## 二、分解（全样本／A）', '', '| 对比 | 标记 | 主读数 全／A | 复利 全／A | 全期回撤 Δ | 滚5回撤 Δ | 复利胜出起点 |',
            '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for p in res['pairs']:
        out.append(f"| {p['arm']} 对 {p['ref']} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | {pp(p['mdd'])} | {pp(p['dd5'])} | "
                   f"{p['better_starts']}/14 |")
    out += ['', '## 三、本题目标：加仓过且水下的持仓占净资产（14 起点中位，时间平均）', '',
            '| 臂 | 规则 | 加仓过且收盘 < 均价 | 加仓过且收盘 < 均价 × 0.9 | 水下 ≥126 日（OI-247 口径） | 水下 ≥252 日 |', '| --- | --- | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        u, o = res['added_uw'][arm], res['occupancy'][arm]
        out.append(f"| {arm} | {rule(arm)} | {pct(u['uw'], 1)} | {pct(u['uw10'], 1)} | {pct(o['occ'][126], 1)} | {pct(o['occ'][252], 1)} |")
    out += ['', '## 四、撤回账（全样本；逐笔按（代码, 日期）跨起点去重）', '',
            '| 臂 | 撤回笔数／路径 | 去重笔数 | 卖出额占净资产中位 | 其中清仓 | 其后 60 日回报 中位／为正 | 其后 250 日 中位／为正 | 250 日内回到均价 | 解锁后再加仓 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in AB_ARMS:
        c = res['cuts'][arm]
        out.append(f"| {arm} | {c['cuts_path']} | {c['unique']} | {pct(c['amount_median'], 1)} | {pct(c['full_share'])} | "
                   f"{pct(c['f60_median'], 1)}／{pct(c['f60_pos'])} | {pct(c['f250_median'], 1)}／{pct(c['f250_pos'])} | "
                   f"{pct(c['recovered'])} | {pct(c['readd'])} |")
    ra = res['ref_adds']
    out += ['', '## 五、加仓闸账（全样本）', '',
            f"对照：S15 实际加仓 {ra['adds']} 次（跨起点按（代码, 信号日）去重），其后 60 日回报中位 {pct(ra['f60_median'], 1)}（为正 {pct(ra['f60_pos'])}），"
            f"250 日 {pct(ra['f250_median'], 1)}（为正 {pct(ra['f250_pos'])}）。", '',
            '| 臂 | 挡下信号日／路径 | 挡下事件／路径 | 事件（跨起点合并） | 涉及代码 | 事件其后 60 日 中位／为正 | 其后 250 日 中位／为正 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in AG_ARMS:
        g = res['gates'][arm]
        out.append(f"| {arm} | {g['days_path']} | {g['events_path']} | {g['events']} | {g['codes']} | {pct(g['f60_median'], 1)}／{pct(g['f60_pos'])} | "
                   f"{pct(g['f250_median'], 1)}／{pct(g['f250_pos'])} |")
    out += ['', f'## 六、中材国际（锚点起点 {ANCHOR}，{CASE_FROM} 起的周期）', '', '| 臂 | 周期（建仓→清仓，退出方式，contrib pp） | 非加仓成交 |', '| --- | --- | --- |']
    for arm in ARMS:
        cs = res['case'][arm]
        tr_ = '；'.join(f"{d} {a} {sh} 股 @{px}（{why}）" for d, a, sh, px, why in res['case_trades'][arm] if a == '卖出') or '—'
        out.append(f"| {arm} | " + ('；'.join(f"{c['entry']}→{c['exit']}，{c['reason']}，{pp(c['contrib'], 1)}" for c in cs) or '未持有') + f" | {tr_} |")
    out += ['', '## 七、风险与集中度（14 起点中位；最深回撤、最低担保比例、滚5最差取跨起点极值）', '',
            '| 臂 | 最深回撤 | 滚5最差（最低） | 最低担保比例 | 强平 | 平均仓位 | 换手 | 持仓只数 | 单票权重中位 | 单票最大 | 前三权重 | 负债到线日 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in ARMS:
        lv = res['levels'][arm]
        out.append(f"| {arm} | {pct(lv['mdd_worst'], 1)} | {pct(lv['worst5_min'], 1)} | {lv['maint_min']:.2f} | {lv['liquidations_max']:.0f} | "
                   f"{pct(lv['平均仓位'])} | {lv['年均换手']:.2f} | {lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | {pct(lv['单票权重最大'])} | "
                   f"{pct(lv['前三权重中位'])} | {pct(res['debt_at_line'][arm])} |")
    out += ['', '## 八、逐年配对差（对 S15；整年在场的起点，中位 pp；括号内为胜出起点数／起点数）', '']
    yrs = sorted({int(y) for v in res['years'].values() for y in v['per_year']})
    out += ['| 对比 | ' + ' | '.join(str(y) for y in yrs) + ' | 胜出年数 |', '| --- |' + ' ---: |' * (len(yrs) + 1)]
    for k, v in res['years'].items():
        cells = [f"{pp(v['per_year'][y]['median'], 1)}（{v['per_year'][y]['better']}/{v['per_year'][y]['n']}）" if y in v['per_year'] else '—' for y in yrs]
        out.append(f"| {k.replace('|', ' 对 ')} | " + ' | '.join(cells) + f" | {v['years_pos']}/{v['years']} |")
    out += ['', '## 九、退出（14 起点中位：周期数／contrib pp）', '', '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' |',
            '| --- | ---: | ---: |' + ' ---: |' * len(EXITS)]
    for arm in ARMS:
        e = res['exits'][arm]
        out.append(f"| {arm} | {e['cycles']} | {e['holding_days_median']} | " + ' | '.join(
            f"{e['count'][n]:.0f}／{pp(e['contrib'][n], 1)}" for _, n in EXITS) + ' |')
    out += ['', '引擎计数（14 起点中位）：' + '；'.join(f"{a} " + '、'.join(f'{k} {v:g}' for k, v in res['stats_keys'][a].items() if v)
                                             for a in ARMS if any(res['stats_keys'][a].values())), '']
    f = res['family']
    out += [f"## 十、第 12 款：本族（OI-233 起的执行层研究）已试 {f['before']} 臂，本批新增 {f['new']} 臂，合计 {f['total']} 臂。", '']
    (EXP / 'readings.md').write_text('\n'.join(out), encoding='utf-8')


if __name__ == '__main__':
    main()
