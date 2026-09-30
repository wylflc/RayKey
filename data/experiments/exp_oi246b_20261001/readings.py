"""OI-246 第二段读数（preregister.md 第 1～8 条）：谷底守卫深跌不买（A2）对 S15（现行 BASE）。
参考读数（全样本／A／U，第 4 款 U 表）、分解、挡下账、OI-246 典型股票、风险与集中度、逐年、退出、第 12 款。

    python3 readings.py     # → readings.json、readings.md
"""
import bisect
import csv
import glob
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
from run import A_SET, ARMS, NEW, REF, TA  # noqa: E402
import prep  # noqa: E402

W5 = sw.WIN5_KEY
STARTS = sw.DEFAULT_STARTS
ANCHOR = sw.EX5_ANCHOR_START
PAIRS = [('TA20', 'TA30'), ('TA40', 'TA30'), ('TV30', 'TA30'), ('DA30', 'TA30')]
YEAR_ARMS = list(NEW)
EXITS = (('移出股票库', '出名单'), ('换仓', '换仓'), ('涨幅', '涨幅减持'), ('股债', '股债上限'), ('强平', '强平'), ('回测截止', '截止清算'))
CLAUSE4 = (('滚动5年年化中位', 0, +1), ('滚动5年年化P25', 0, +1), ('滚动5年年化最差', 0, +1), ('滚动5年回撤中位', 0, -1),
           ('滚动5年Calmar中位', 1, +1), ('滚动5年Sharpe中位', 1, +1), ('滚动5年为负的窗口占比', 0, -1), ('年化', 0, +1),
           ('最大回撤', 0, -1), ('Calmar', 1, +1), ('Sharpe', 1, +1), ('互不重叠5年块中位', 0, +1), ('滚动3年年化中位', 0, +1),
           ('滚动3年回撤中位', 0, -1), ('逐年收益中位', 0, +1), ('逐年最差', 0, +1))
CONC = ('持仓数中位', '单票权重中位', '单票权重P90', '单票权重最大', '前三权重中位', '单票超60%天数占比')
CREDIT = 0.666
FAMILY_BEFORE = 126           # OI-233～OI-247 已试臂数（OI-247 止）
GAP = 20                      # 同一代码相隔超过 20 个交易日再挡下算新事件
TYPICAL = ROOT / 'data/experiments/exp_oi246_20260930/readings.json'


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


# ── 挡下条件（按状态逐日判，与路径无关）───────────────────────────────────────────────────────────────

class Cond:
    """v（prep.py 分段）与 250 日回报（按正式公司行动折到当日口径，同引擎补丁）。"""

    def __init__(self, codes):
        self.v = {}
        with prep.OUT.open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                days, vals = self.v.setdefault(r['security_code'], ([], []))
                days.append(r['from'])
                vals.append(float(r['v']))
        actions = bt.load_actions()
        closes = bt.load_prices(codes)
        self.s = {}
        for c in codes:
            days = sorted(closes.get(c, {}))
            if days:
                a, b = bt.exright_affine(days, actions.get(c, {}))
                self.s[c] = (days, [a[i] * closes[c][d] + b[i] for i, d in enumerate(days)], b)

    def vv(self, code, day):
        seq = self.v.get(code)
        if not seq:
            return 0.0
        j = bisect.bisect_right(seq[0], day) - 1
        return seq[1][j] if j >= 0 else 0.0

    def ret250(self, code, day):
        if code not in self.s:
            return None
        days, q, b = self.s[code]
        i = bisect.bisect_right(days, day) - 1
        if i < 250 or days[i] != day:
            return None
        den = q[i - 250] - b[i]
        return (q[i] - b[i]) / den - 1 if den > 0 else None

    def flagged(self, arm, code, day):
        vmin, drop = TA[arm]
        r = self.ret250(code, day)
        return r is not None and r < -drop and self.vv(code, day) >= vmin


def gap(T, code, a, b):
    days = T.s[code][0] if code in T.s else None
    if not days:
        return GAP + 1
    return bisect.bisect_right(days, b) - bisect.bisect_right(days, a)


# ── 读数第 3 条：挡下账 ──────────────────────────────────────────────────────────────────────────────

def s15_entries(arms_trades, T):
    """S15 全部新建仓（跨起点按（代码, 信号日）去重）与各起点周期。"""
    out = {}
    for s, cycles in arms_trades[REF].items():
        for x in cycles:
            code = x['security_code'].zfill(6)
            sig = T.prev(code, x['entry_date'])
            if sig:
                out.setdefault((code, sig), []).append((s, x))
    return out


def block_ledger(arm, T, C, entries):
    per_days, per_events, union = [], [], defaultdict(set)
    for s in STARTS:
        with (EXP / 'blocks' / f'{tag(arm, s)}.csv').open(newline='', encoding='utf-8') as f:
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
    hit = [(k, v) for k, v in entries.items() if C.flagged(arm, *k)]
    contrib = [float(x['contrib'] or 0) for _k, v in hit for _s, x in v]
    return dict(days_path=med(per_days), events_path=med(per_events), events=len(events), codes=len(union),
                f60_median=med(f60), f60_pos=_share(f60, lambda z: z > 0), f250_median=med(f250), f250_pos=_share(f250, lambda z: z > 0),
                s15_flagged_entries=len(hit), s15_flagged_cycles=len(contrib), s15_flagged_contrib=sum(contrib),
                s15_flagged_win=_share([float(x['return_pct'] or 0) for _k, v in hit for _s, x in v], lambda z: z > 0),
                s15_flagged_f250=med([T.fwd(k[0], k[1], 250) for k, _v in hit]))


def ref_entries_fwd(entries, T):
    f60 = [T.fwd(c, d, 60) for c, d in entries]
    f250 = [T.fwd(c, d, 250) for c, d in entries]
    allc = [float(x['contrib'] or 0) for v in entries.values() for _s, x in v]
    return dict(entries=len(entries), f60_median=med(f60), f60_pos=_share(f60, lambda z: z > 0),
                f250_median=med(f250), f250_pos=_share(f250, lambda z: z > 0), cycles=len(allc), contrib=sum(allc))


def _share(xs, cond):
    xs = [x for x in xs if x is not None]
    return sum(1 for x in xs if cond(x)) / len(xs) if xs else None


# ── 读数第 4 条：OI-246 典型股票 ───────────────────────────────────────────────────────────────────────

def _shift_month(month, k):
    y, m = int(month[:4]), int(month[5:7]) + k
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f'{y:04d}-{m:02d}'


def typical(entries, C):
    out = []
    for t in json.loads(TYPICAL.read_text(encoding='utf-8'))['typical']:
        lo, hi = _shift_month(t['month'], -12), _shift_month(t['month'], 12)
        rows = []
        for (code, sig), v in sorted(entries.items(), key=lambda kv: kv[0][1]):
            if code == t['code'] and lo <= sig[:7] <= hi:
                rows.append(dict(sig=sig, cycles=len(v), contrib=statistics.mean(float(x['contrib'] or 0) for _s, x in v),
                                 ret250=C.ret250(code, sig), v=C.vv(code, sig), flagged={a: C.flagged(a, code, sig) for a in NEW}))
        out.append(dict(code=t['code'], name=t['name'], cls=t['cls'], month=t['month'], a2=bool(t['A2']), entries=rows))
    return out


def main():
    arms_trades = {a: trades_of(a) for a in ARMS}
    codes = {c['security_code'].zfill(6) for st in arms_trades.values() for cs in st.values() for c in cs}
    for a in NEW:
        for s in STARTS:
            with (EXP / 'blocks' / f'{tag(a, s)}.csv').open(newline='', encoding='utf-8') as f:
                codes |= {r['code'].zfill(6) for r in csv.DictReader(f)}
    codes |= {t['code'] for t in json.loads(TYPICAL.read_text(encoding='utf-8'))['typical']}
    T = TR(codes)
    C = Cond(codes)
    nm = names()
    entries = s15_entries(arms_trades, T)
    years = {a: year_returns(a) for a in [REF] + YEAR_ARMS}
    res = dict(ref=REF, A=A_SET, levels={a: levels(a) for a in ARMS}, vs_base={a: vs_base(a) for a in NEW},
               pairs=[pair(a, r) for a, r in PAIRS], years={f'{a}|{REF}': year_pair(years[a], years[REF]) for a in YEAR_ARMS},
               exits=exits(arms_trades), debt_at_line={a: debt_at_line(a) for a in ARMS},
               blocks={a: block_ledger(a, T, C, entries) for a in NEW}, ref_entries=ref_entries_fwd(entries, T),
               typical=typical(entries, C),
               stats_keys={a: {k: med([stats_of(a, s).get(k, 0) for s in STARTS]) for k in ('前低建仓', 'A2·深跌挡下建仓')} for a in ARMS},
               family=dict(before=FAMILY_BEFORE, new=len(NEW), total=FAMILY_BEFORE + len(NEW)))
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    write_md(res, nm)


def write_md(res, nm):
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    pp = lambda x, d=2: '—' if x is None or x != x else f'{x * 100:+.{d}f}'
    trio = lambda xs: '／'.join(pp(x) for x in xs)
    rule = lambda a: ('现行' if a == REF else
                      f"{'v ≥ 0.5' if TA[a][0] == 0.5 else 'v > 0' if TA[a][0] > 0 else '不看 v'}·250 日跌幅 > {TA[a][1]:.0%} 不建仓")
    out = ['# OI-246 第二段读数（v4.225 状态，买入线 1.0034，14 起点；参照 S15 = 现行 BASE）', '',
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
    out += ['', '## 二、分解（全样本／A）', '', '| 对比 | 标记 | 主读数 全／A | 复利 全／A | 全期回撤 Δ | 滚5回撤 Δ | 复利胜出起点 |',
            '| --- | --- | --- | --- | ---: | ---: | ---: |']
    for p in res['pairs']:
        out.append(f"| {p['arm']} 对 {p['ref']} | {p['flag']} | {trio(p['main'])} | {trio(p['cagr'])} | {pp(p['mdd'])} | {pp(p['dd5'])} | "
                   f"{p['better_starts']}/14 |")
    re_ = res['ref_entries']
    out += ['', '## 三、挡下账（全样本）', '',
            f"对照：S15 全部新建仓 {re_['entries']} 个（跨起点按（代码, 信号日）去重），其后 60 日回报中位 {pct(re_['f60_median'], 1)}（为正 {pct(re_['f60_pos'])}），"
            f"250 日 {pct(re_['f250_median'], 1)}（为正 {pct(re_['f250_pos'])}）；闭合周期 {re_['cycles']} 个，contrib 合计 {pp(re_['contrib'], 1)}pp。", '',
            '| 臂 | 挡下信号日／路径 | 挡下事件／路径 | 事件（跨起点合并） | 涉及代码 | 事件其后 60 日 中位／为正 | 其后 250 日 中位／为正 | '
            'S15 建仓满足挡下条件的 | 其闭合周期 | 其 S15 contrib 合计 | 其周期回报为正 | 其信号日后 250 日回报中位 |',
            '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for arm in NEW:
        b = res['blocks'][arm]
        out.append(f"| {arm} | {b['days_path']} | {b['events_path']} | {b['events']} | {b['codes']} | {pct(b['f60_median'], 1)}／{pct(b['f60_pos'])} | "
                   f"{pct(b['f250_median'], 1)}／{pct(b['f250_pos'])} | {b['s15_flagged_entries']} | {b['s15_flagged_cycles']} | "
                   f"{pp(b['s15_flagged_contrib'], 1)} | {pct(b['s15_flagged_win'])} | {pct(b['s15_flagged_f250'], 1)} |")
    out += ['', '挡下事件：同一代码相隔超过 20 个交易日再挡下算新事件。「S15 建仓满足挡下条件」按状态逐日判（与路径无关）；'
            '其 contrib 为这些周期在 S15 各起点的贡献之和（为负即本臂避开了亏损）。']
    out += ['', '## 四、OI-246 典型股票（入选月前后 12 个月内 S15 的新建仓）', '',
            '| 代码 | 名称 | 结局 | 入选月 | OI-246 A2 | S15 建仓信号日（起点数，contrib 均值 pp，250 日回报，v，挡下臂） |', '| --- | --- | --- | --- | --- | --- |']
    for t in res['typical']:
        cells = '；'.join(f"{e['sig']}（{e['cycles']}，{pp(e['contrib'], 1)}，{pct(e['ret250'], 0) if e['ret250'] is not None else '—'}，"
                          f"{e['v']:.2f}，{'／'.join(a for a, f in e['flagged'].items() if f) or '无'}）" for e in t['entries']) or 'S15 未建仓'
        out.append(f"| {t['code']} | {t['name']} | {t['cls']} | {t['month']} | {'是' if t['a2'] else '否'} | {cells} |")
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
    out += ['', '## 七、退出（14 起点中位：周期数／contrib pp）', '', '| 臂 | 周期数 | 持有天数中位 | ' + ' | '.join(n for _, n in EXITS) + ' |',
            '| --- | ---: | ---: |' + ' ---: |' * len(EXITS)]
    for arm in ARMS:
        e = res['exits'][arm]
        out.append(f"| {arm} | {e['cycles']} | {e['holding_days_median']} | " + ' | '.join(
            f"{e['count'][n]:.0f}／{pp(e['contrib'][n], 1)}" for _, n in EXITS) + ' |')
    out += ['', '引擎计数（14 起点中位）：' + '；'.join(f"{a} " + '、'.join(f'{k} {v:g}' for k, v in res['stats_keys'][a].items() if v)
                                             for a in ARMS), '']
    f = res['family']
    out += [f"## 八、第 12 款：本族（OI-233 起的执行层研究）已试 {f['before']} 臂，本批新增 {f['new']} 臂，合计 {f['total']} 臂。", '']
    (EXP / 'readings.md').write_text('\n'.join(out), encoding='utf-8')


if __name__ == '__main__':
    main()
