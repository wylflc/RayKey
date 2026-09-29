"""OI-237 读数（preregister.md 第 1～7 条），参照臂 BASE：
对 BASE 的叠加读数（全样本／A／U，第 4 款 U 表标记）、2×2 分解与对 BTNS 的增量、一档 3%／4%／5% 与 CC 对 S 的直接对比
（全样本／A／UC 与逐年）、第 13 款、第 11 款案例归因、执行与行为。

    python3 readings.py     # → readings.json、readings.md、case_<臂>_vs_<参照>.md
"""
import bisect
import csv
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
from run import ACTIONS, ARMS, CELLS, LINE, REF, STATES  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
CTX = ('NS', 'BTNS', 'BS15')                                   # 分解用的参照臂
PKG = [a for a in ARMS if a not in (REF, *CTX)]                # 组合臂
TRANCHE = ([(f'X3{c}', c) for c in CELLS] + [(f'X3CC{c}', f'CC{c}') for c in CELLS] + [('NSX3S15', 'NSS15'), ('NSX3CCS15', 'NSCCS15')])
DOSE = [('X4S15', 'S15'), ('X3S15', 'X4S15'), ('X4CCS15', 'CCS15'), ('X3CCS15', 'X4CCS15')]
TRIGGER = [(f'CC{c}', c) for c in CELLS] + [(f'X3CC{c}', f'X3{c}') for c in CELLS] + [('NSCCS15', 'NSS15'), ('NSX3CCS15', 'NSX3S15')]
YEAR_PAIRS = [('S15', REF), ('X3S15', REF), ('CCS15', REF), ('X3CCS15', REF), ('X3S15', 'S15'), ('X3CCS15', 'CCS15'),
              ('CCS15', 'S15'), ('X3CCS15', 'X3S15')]
CASE_PAIRS = [(a, REF) for a in ('S15', 'X3S15', 'CCS15', 'X3CCS15', 'BS15')] + [('X3S15', 'S15'), ('CCS15', 'S15'), ('X3CCS15', 'X3S15')]
CASES = ('O01', 'O02', 'O03', 'O05', 'O08', 'O10', 'T01', 'T02', 'T11')
EXITS = (('止损', '止损'), ('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'), ('强平', '强平'), ('回测截止', '截止清算'))
DIAG = ('诊断·持有高估日', '诊断·资金不足日', '诊断·资金不足且无未持仓候选', '诊断·资金不足且持有高估', '诊断·持有高估且无触发者')
# 第 4 款「去赢家全面优秀」的标准指标集（不计长跑锚点、换手、仓位与集中度表）：（列, 比率项, 变好方向）
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
CREDIT = 0.666


def load(path):
    sw.set_market(sw.scan_market(path))
    groups, _orders, failed, *_ = sw.load_scan(path)
    assert not any(failed.values()), (path, failed)
    return groups


FULL = load(EXP / 'sweep_full.txt')['']
EXA = load(EXP / 'sweep_A.txt')[sw.EX5_PREFIX]
EXUC = load(EXP / 'sweep_UC.txt')[sw.EX5_PREFIX]
EXU = {a: load(EXP / 'u' / f'{a}.txt')[sw.EX5_PREFIX] for a in ARMS if a != REF}


def pm(grp, arm, key, ref=REF):
    return sw._paired_median(grp, arm, key, ref=ref)


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

    def low(self, code, a, b):
        days, tr = self.s[code]
        seg = days[bisect.bisect_left(days, a):bisect.bisect_right(days, b)]
        return min(tr[d] for d in seg) if seg else None


# ── 参考读数 ─────────────────────────────────────────────────────────────────────────────────────────────

def clause4(arm):
    """§12.1 第 4 款：U 表标准指标集各项配对差中位（变好方向）均不劣于噪声带，或至多一项落在 [容差, 噪声带)。
    百分率项噪声带 −0.15pp、容差 −1pp；Calmar、Sharpe 四项 −0.005、−0.033。"""
    grp, items, bad = EXU[arm], [], []
    for key, ratio, good in CLAUSE4:
        d = pm(grp, arm, key) * good
        noise, tol = (0.005, 0.033) if ratio else (0.0015, 0.01)
        items.append((key, d))
        if d < -noise:
            bad.append((key, d, d >= -tol))
    ok = not bad or (len(bad) == 1 and bad[0][2])
    return dict(ok=ok, bad=[(k, d) for k, d, _ in bad], items=items)


def levels(arm):
    col = lambda key: [FULL[arm][s][key] for s in STARTS]
    out = {k: statistics.median(col(k)) for k in ('年化', '最大回撤', '滚动5年年化中位', '滚动5年回撤中位', '平均仓位', '年均换手', *CONC)}
    out.update(mdd_worst=max(col('最大回撤')), maint_min=min(col('最低担保比例')), buffer_min=min(col('最低股票同跌缓冲')),
               liquidations_max=max(col('强平次数')), worst5_min=min(col('滚动5年年化最差')))
    return out


def vs_base(arm):
    flag, reasons, vals = sw.reading_flags(FULL, EXA, arm, ref=REF)
    u = EXU[arm]
    eps = vals['回撤段']
    return dict(flag=flag, reasons=reasons,
                main=[pm(FULL, arm, W5), pm(EXA, arm, W5), pm(u, arm, W5)],
                cagr=[pm(FULL, arm, '年化'), pm(EXA, arm, '年化'), pm(u, arm, '年化')],
                mdd=[pm(FULL, arm, '最大回撤'), pm(EXA, arm, '最大回撤')], dd5=pm(FULL, arm, '滚动5年回撤中位'),
                p25=pm(FULL, arm, '滚动5年年化P25'), worst5=pm(FULL, arm, '滚动5年年化最差'),
                episodes=[dict(start=ep['start'], end=ep['end'], n=ep['n'], delta=ep['delta']) for ep in eps],
                shallower=sum(ep['delta'] <= -sw.DD_PATH_MDD_GAIN for ep in eps),
                better_starts=sum(FULL[arm][s]['年化'] > FULL[REF][s]['年化'] for s in STARTS),
                vs_btns=[pm(FULL, arm, W5, 'BTNS'), pm(EXA, arm, W5, 'BTNS'), pm(FULL, arm, '年化', 'BTNS'), pm(EXA, arm, '年化', 'BTNS')]
                if arm not in (REF, 'BTNS', 'NS', 'BS15') else None,
                clause4=clause4(arm))


def combo(grp, plus, minus, key):
    """逐起点把 Σ(+臂) − Σ(−臂) 合成（主读数同窗先合成再取起点内中位），再取跨起点中位；2×2 交互项用。"""
    vals = []
    for s in STARTS:
        if key == W5:
            ws = [grp[a][s][W5] for a in (*plus, *minus)]
            months = set(ws[0])
            assert all(set(w) == months for w in ws), s
            vals.append(statistics.median(sum(grp[a][s][W5][m] for a in plus) - sum(grp[a][s][W5][m] for a in minus) for m in months))
        else:
            vals.append(sum(grp[a][s][key] for a in plus) - sum(grp[a][s][key] for a in minus))
    return statistics.median(vals)


def two_by_two():
    """建仓止损（BASE→BTNS）× 换仓源（现行弱势＋边际 → S15 让位）。"""
    rows = (('BTNS 对 BASE（现行换仓下的建仓止损效应）', ['BTNS'], [REF]), ('BS15 对 BASE（现行建仓止损下的让位效应）', ['BS15'], [REF]),
            ('S15 对 BTNS（BTNS 下的让位效应）', ['S15'], ['BTNS']), ('S15 对 BS15（让位下的建仓止损效应）', ['S15'], ['BS15']),
            ('S15 对 BASE（合计）', ['S15'], [REF]), ('交互项 =（S15 − BTNS）−（BS15 − BASE）', ['S15', REF], ['BTNS', 'BS15']))
    return [dict(name=n, main=[combo(g, p, m, W5) for g in (FULL, EXA)], cagr=[combo(g, p, m, '年化') for g in (FULL, EXA)],
                 mdd=combo(FULL, p, m, '最大回撤')) for n, p, m in rows]


def year_returns(arm):
    """整年在场的起点：{年: {起点: 年收益}}；年收益 = 年末净资产 ÷ 上年末 − 1，2026 为截至末次净值日。"""
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
                mdd=pm(FULL, arm, '最大回撤', ref), dd5=pm(FULL, arm, '滚动5年回撤中位', ref), p25=pm(FULL, arm, '滚动5年年化P25', ref),
                better_starts=sum(FULL[arm][s]['年化'] > FULL[ref][s]['年化'] for s in STARTS),
                holdings=[statistics.median(FULL[a][s]['持仓数中位'] for s in STARTS) for a in (arm, ref)],
                top1_max=[statistics.median(FULL[a][s]['单票权重最大'] for s in STARTS) for a in (arm, ref)],
                years=year_pair(years[arm], years[ref]))


# ── 执行、陷阱与行为（OI-236 同口径，参照改为 BASE）─────────────────────────────────────────────────────────

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
        out[arm] = dict(episodes=len(recognized), pairs=len(pairs), never_held=1 - len(h) / len(pairs),
                        churn_3plus=sum(p['cycles'] >= 3 for p in h) / len(h), cycles_median=med([p['cycles'] for p in h]),
                        premium_median=med([p['prem'] for p in firsts]), delay_median=med([p['delay'] for p in firsts]),
                        in_market_median=med([p['in_market'] for p in h]), wprem_median=med(wp),
                        wprem_p75=float(np.percentile(wp, 75)) if wp else None)
    return out


def trap_readings(rows, arms_trades, rng):
    """陷阱段：按建仓月标签的 contrib（跨起点中位）、持有天数；对 BASE 的差值按股票整簇自助。"""
    label_at = {(r['code'], r['month']): r['label'] for r in rows}
    per = {}
    for arm, starts in arms_trades.items():
        by_code = defaultdict(lambda: [0.0] * len(starts))
        days_in = defaultdict(lambda: [0.0] * len(starts))
        for i, (_start, cycles) in enumerate(sorted(starts.items())):
            for c in cycles:
                code = c['security_code'].zfill(6)
                if label_at.get((code, c['entry_date'][:7])) == audit.TRAP:
                    by_code[code][i] += float(c['contrib'] or 0)
                    days_in[code][i] += (date.fromisoformat(c['exit_date'] or '2026-08-28') - date.fromisoformat(c['entry_date'])).days
        per[arm] = (by_code, days_in)
    codes = sorted({c for bc, _ in per.values() for c in bc})
    idx = {c: i for i, c in enumerate(codes)}

    def matrix(arm, which):
        m = np.zeros((len(codes), len(STARTS)))
        for c, v in per[arm][which].items():
            m[idx[c]] = v
        return m
    ref_c, ref_d = matrix(REF, 0), matrix(REF, 1)
    draws = [np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float) for _ in range(1000)]
    stat = lambda m, w=None: float(np.median((m if w is None else m * w[:, None]).sum(axis=0)))
    out = {}
    for arm in arms_trades:
        mc, md = matrix(arm, 0), matrix(arm, 1)
        dc = [stat(mc, w) - stat(ref_c, w) for w in draws]
        out[arm] = dict(trap_contrib=stat(mc), trap_days=stat(md), d_contrib=stat(mc) - stat(ref_c),
                        d_contrib_ci=[float(np.percentile(dc, 5)), float(np.percentile(dc, 95))], d_days=stat(md) - stat(ref_d))
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


def t_account(S):
    """让位账：tlog 的盈利偏离让位减仓；其后 60 个交易日；「卖出对持有 60 日」= Σ(−60 日回报 × 减仓金额 ÷ 净资产) ÷ 起点数。"""
    out = {}
    for arm in [a for a, args in ARMS.items() if '--swap-ext' in args]:
        per, f60, sold60 = [], [], []
        for s in STARTS:
            log = json.loads((EXP / 'tlog' / f'{tag(arm, s)}.json').read_text())
            nav = nav_of(arm, s)
            trims = [x for x in log if x[0] == 'trim']
            per.append(len(trims))
            for x in trims:
                b = S.fwd_days(x[1], x[2], 60)
                f60.append(b)
                if b is not None and x[2] in nav:
                    sold60.append(-b * x[3] * x[4] / nav[x[2]][0])
        n60 = [x for x in f60 if x is not None]
        out[arm] = dict(trims_median=med(per), fwd60_median=med(f60), fwd60_up10=sum(x > 0.10 for x in n60) / max(1, len(n60)),
                        sold_vs_hold60_pp=sum(sold60) / len(STARTS))
    return out


def swap_account(arms_trades):
    """换仓卖出笔数（逐笔流水「让位给」，逐起点中位）与由已持仓候选触发的占比。"""
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


def diagnostics():
    out = {}
    for arm in ARMS:
        vals = defaultdict(list)
        for s in STARTS:
            st = json.loads((EXP / 'stats' / f'{tag(arm, s)}.json').read_text())
            days = len(nav_of(arm, s))
            short = st.get('诊断·资金不足日', 0)
            vals['rich_days'].append(st.get('诊断·持有高估日', 0) / days)
            vals['short_days'].append(short / days)
            vals['short_no_trigger'].append(st.get('诊断·资金不足且无未持仓候选', 0) / short if short else None)
            vals['rich_no_trigger_days'].append(st.get('诊断·持有高估且无触发者', 0) / days)
        out[arm] = {k: med(v) for k, v in vals.items()}
    return out


def debt_at_line(arm):
    return med([sum(debt >= CREDIT * e - 1 for e, debt, _ in nav.values() if e > 0) / len(nav) for nav in (nav_of(arm, s) for s in STARTS)])


def top3_share(arm, ref):
    """第 11 款：前三只（与总差同号、按贡献差排序）贡献差之和 ÷ 总差（锚点起点，contrib 口径）。"""
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
    manifest = json.loads((EXP / 'run_manifest.json').read_text())
    res = dict(line=LINE, ref=REF, sets=dict(A=manifest['A'], top5=manifest['top5'], U=manifest['U'], UC=manifest['UC'],
                                             UC_cover={a: set(t) <= set(manifest['UC']) for a, t in manifest['top5'].items()}),
               levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in ARMS if a != REF}, two_by_two=two_by_two(),
               tranche=[pair(a, r, years) for a, r in TRANCHE], dose=[pair(a, r, years) for a, r in DOSE],
               trigger=[pair(a, r, years) for a, r in TRIGGER], years={f'{a}|{r}': year_pair(years[a], years[r]) for a, r in YEAR_PAIRS},
               execution=execution(eps, pv, arms_trades, S), traps=trap_readings(rows, arms_trades, np.random.default_rng(20260930)),
               exits=exits(arms_trades), t_account=t_account(S), swap_account=swap_account(arms_trades), diagnostics=diagnostics(),
               debt_at_line={a: debt_at_line(a) for a in ARMS}, strategy={}, cases={})
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
    write_md(res, cases)


def write_md(res, cases):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)
    arms = list(ARMS)
    sets = res['sets']
    out = [f'# OI-237 读数（v4.221 状态，买入线 {LINE}，14 起点；参照臂 {REF}）', '',
           'Δ 均为逐起点配对差中位（pp）。主读数 = 同窗口滚 5 年化配对差；复利读数 = 全期 CAGR 配对差。读数只作裁定参考。', '',
           f"剔除集：A = {'/'.join(sets['A'])}；UC = {'/'.join(sets['UC'])}；各臂 U = A ∪ 该臂锚点前五（见 readings.json）。"
           f"前五不全在 UC 内的臂：{'、'.join(a for a, ok in sets['UC_cover'].items() if not ok) or '无'}。", '',
           '## 一、对 BASE 的叠加读数', '',
           '| 臂 | 标记 | 主读数 全／A／U | 复利 全／A／U | 第 4 款 U | 年化 | 最大回撤 | 全期回撤 Δ 全／A | 滚5回撤 Δ | 滚5 P25 Δ | 滚5最差 Δ | 更浅≥5pp 回撤段 | 复利胜出起点 |',
           '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        if arm == REF:
            out.append(f"| {REF}（参照） | — | — | — | — | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | — | — | — | — | — | — |")
            continue
        r = res['vs_base'][arm]
        c4 = '去赢家全面优秀' if r['clause4']['ok'] else '未满足'
        c4 += '' if not r['clause4']['bad'] else '（' + '、'.join(f"{k} {d * (1 if k in ('滚动5年Calmar中位', '滚动5年Sharpe中位', 'Calmar', 'Sharpe') else 100):+.2f}"
                                                              for k, d in r['clause4']['bad']) + '）'
        out.append(f"| {arm} | {r['flag']} | {trio(r['main'])} | {trio(r['cagr'])} | {c4} | {pct(lv['年化'], 1)} | {pct(lv['最大回撤'], 1)} | "
                   f"{trio(r['mdd'])} | {pp(r['dd5'])} | {pp(r['p25'])} | {pp(r['worst5'])} | {r['shallower']}/{len(r['episodes'])} | {r['better_starts']}/14 |")
    out += ['', '## 二、分解', '', '### 2×2：建仓止损 × 换仓源（逐起点合成后取中位）', '',
            '| 项 | 主读数 全／A | 复利 全／A | 全期回撤 Δ |', '| --- | ---: | ---: | ---: |']
    for x in res['two_by_two']:
        out.append(f"| {x['name']} | {trio(x['main'])} | {trio(x['cagr'])} | {pp(x['mdd'])} |")
    out += ['', '### 组合各臂对 BTNS 的增量（A = BASE 前五）', '', '| 臂 | 主读数 全／A | 复利 全／A |', '| --- | ---: | ---: |']
    for arm in PKG:
        v = res['vs_base'][arm]['vs_btns']
        if v:
            out.append(f'| {arm} | {trio(v[:2])} | {trio(v[2:])} |')
    for title, key, note in (('三、一档 3% 对 5%（同格同触发；参照 = 5% 臂）', 'tranche', ''),
                             ('三（续）、S15 格剂量 3→4→5%', 'dose', ''),
                             ('四、已持仓触发 CC 对只由未持仓触发 S（同格同档；参照 = S 臂）', 'trigger', '')):
        out += ['', f'## {title}', '',
                '| 臂 | 参照 | 标记 | 主读数 全／A／UC | 复利 全／A／UC | 全期回撤 Δ | 滚5回撤 Δ | 滚5 P25 Δ | 复利胜出起点 | 逐年胜出年数 | 持仓只数 | 单票最大权重 |',
                '| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for p in res[key]:
            out.append(f"| {p['arm']} | {p['ref']} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | {pp(p['mdd'])} | {pp(p['dd5'])} | "
                       f"{pp(p['p25'])} | {p['better_starts']}/14 | {p['years']['years_pos']}/{p['years']['years']} | "
                       f"{p['holdings'][0]:.0f}／{p['holdings'][1]:.0f} | {pct(p['top1_max'][0])}／{pct(p['top1_max'][1])} |")
    yrs = sorted({int(y) for v in res['years'].values() for y in v['per_year']})
    out += ['', '## 五、逐年配对差（整年在场的起点，中位 pp；括号内为胜出起点数／起点数）', '',
            '| 对比 | ' + ' | '.join(str(y) for y in yrs) + ' | 胜出年数 |', '| --- |' + ' ---: |' * (len(yrs) + 1)]
    for k, v in res['years'].items():
        cells = [f"{pp(v['per_year'][y]['median'], 1)}（{v['per_year'][y]['better']}/{v['per_year'][y]['n']}）" if y in v['per_year'] else '—'
                 for y in yrs]
        out.append(f"| {k.replace('|', ' 对 ')} | " + ' | '.join(cells) + f" | {v['years_pos']}/{v['years']} |")
    out += ['', '## 六、风险与集中度（14 起点中位；最深回撤、最低担保比例与缓冲取跨起点极值）', '',
            '| 臂 | 最深回撤 | 滚5最差（最低） | 最低担保比例 | 最低股票同跌缓冲 | 强平 | 平均仓位 | 换手 | 持仓只数 | 单票权重中位 | 单票 P90 | 单票最大 | 前三权重 | 单票超60%天数 | 负债到线日 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in arms:
        lv = res['levels'][arm]
        out.append(f"| {arm} | {pct(lv['mdd_worst'], 1)} | {pct(lv['worst5_min'], 1)} | {lv['maint_min']:.2f} | {pct(lv['buffer_min'])} | "
                   f"{lv['liquidations_max']:.0f} | {pct(lv['平均仓位'])} | {lv['年均换手']:.2f} | {lv['持仓数中位']:.0f} | {pct(lv['单票权重中位'])} | "
                   f"{pct(lv['单票权重P90'])} | {pct(lv['单票权重最大'])} | {pct(lv['前三权重中位'])} | {pct(lv['单票超60%天数占比'], 1)} | "
                   f"{pct(res['debt_at_line'][arm])} |")
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
    names = {c['case_id']: f"{c['security_name']} {c['window_start']}～{c['window_end']}" for c in cases}
    out += ['', '### 具名案例（持有过的起点数／可比起点数，contrib 中位 pp）', '',
            '| 臂 | ' + ' | '.join(f'{k} {names.get(k, "")}' for k in CASES) + ' |', '| --- |' + ' ---: |' * len(CASES)]
    for arm in arms:
        cs = res['strategy'][arm]['cases']
        out.append(f'| {arm} | ' + ' | '.join(f"{cs[k]['held_starts']}/{cs[k]['starts']}，{pp(cs[k]['contrib_median'])}" if k in cs else '—'
                                              for k in CASES) + ' |')
    out += ['', '## 九、第 11 款案例归因（锚点起点 2011-11-01；全表见 case_<臂>_vs_<参照>.md）', '']
    for k, v in res['cases'].items():
        t3 = v['top3']
        out += [f"### {k.replace('|', ' 对 ')}：总差 {pp(t3['total'], 1)}pp，前三只 " + '、'.join(f'{c} {pp(x, 1)}' for c, x in t3['top3'])
                + f"，净额占比 {pct(t3['share'])}", '', '| 公司 | Δ | 归类 | 依据 |', '| --- | ---: | --- | --- |', *v['table'], '']
    out += ['## 十、退出、换仓与诊断（14 起点中位）', '',
            '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' | 换仓卖出笔数 | 已持仓触发 | 持有高估且无触发者 |',
            '| --- | ---: | ---: |' + ' ---: |' * (len(EXITS) + 3)]
    for arm in arms:
        x, s, d = res['exits'][arm], res['swap_account'][arm], res['diagnostics'][arm]
        out.append(f"| {arm} | {x['cycles']} | {x['holding_days_median']} | " + ' | '.join(f"{x['count'][n]:.0f}／{pp(x['contrib'][n], 1)}" for _, n in EXITS)
                   + f" | {s['swaps_median']:.0f} | {pct(s['held_trigger_share'])} | {pct(d['rich_no_trigger_days'])} |")
    out += ['', '### 让位账（盈利偏离让位减仓；「卖出对持有 60 日」正为卖对）', '',
            '| 臂 | 让位减仓次数中位 | 减仓后 60 日中位 | 60 日再涨 >10% | 卖出对持有 60 日 pp |', '| --- | ---: | ---: | ---: | ---: |']
    for arm, t in res['t_account'].items():
        out.append(f"| {arm} | {t['trims_median']:.0f} | {pct(t['fwd60_median'], 1)} | {pct(t['fwd60_up10'])} | {pp(t['sold_vs_hold60_pp'])} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out[:60]))


if __name__ == '__main__':
    main()
