"""OI-246 谷底守卫典型股票探索（preregister.md 一～四、读数 1～3）。

观测取 `../exp_oi245c_20260930/observations3.csv`（R1 的公允性 λ 已在 `../exp_oi245c_20260930/readings3.md` 第三节出）；
行情按正式公司行动前复权（引擎 `exright_affine` 同式）。读数第 4 条（现行 BASE 实际持仓）见 `../exp_oi247_20260930/readings.md`。

    python3 analyze.py     # → episodes.csv、readings.json、readings.md
"""
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt  # noqa: E402

OBS = ROOT / 'data/experiments/exp_oi245c_20260930/observations3.csv'
LINE, PV_RANGE, SEED, BOOT = 1.0034, (0.2, 5.0), 20260930, 1000
FIXED = (('000568', '2015'), ('002841', '2022'))           # 泸州老窖 2015 年段、视源股份 2022 年段
HORIZON = 756


def fnum(v):
    return None if v in ('', 'None', None) else float(v)


def load_rows():
    out = []
    with OBS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['panel'] != 'True' or fnum(r['f3']) is None or not PV_RANGE[0] <= float(r['pv']) <= PV_RANGE[1] or r['month'] < '2007-01':
                continue
            out.append(dict(code=r['code'], name=r['name'], month=r['month'], date=r['date'], pv=float(r['pv']), f3=float(r['f3']),
                            v=fnum(r['v']) or 0.0, F1=fnum(r['F1']), pr=fnum(r['pr']), br=fnum(r['br']), pv_R1=fnum(r['pv_R1'])))
    return out


def month_no(m):
    return int(m[:4]) * 12 + int(m[5:7])


def episodes(rows):
    med = defaultdict(list)
    for r in rows:
        med[r['month']].append(r['f3'])
    med = {m: statistics.median(v) for m, v in med.items()}
    by = defaultdict(list)
    for r in rows:
        by[r['code']].append(r)
    out = []
    for code, rs in by.items():
        rs.sort(key=lambda r: r['month'])
        run = []
        for r in rs + [None]:
            if r is not None and r['v'] > 0 and (not run or month_no(r['month']) - month_no(run[-1]['month']) <= 2):
                run.append(r)
                continue
            if run:
                entry = next((x for x in run if x['v'] >= 0.5 and x['pv'] <= LINE), None)
                if entry:
                    ex = entry['f3'] - med[entry['month']]
                    out.append(dict(entry, first=run[0]['month'], last=run[-1]['month'], excess=ex,
                                    cls='恢复' if ex >= 0.05 else '陷阱' if ex <= -0.05 else '中性'))
            run = [r] if r is not None and r['v'] > 0 else []
    return out


class Prices:
    def __init__(self, codes):
        actions = bt.load_actions()
        closes, lows = bt._load_ohlcv_column('close', codes), bt._load_ohlcv_column('low', codes)
        self.s = {}
        for c in codes:
            days = sorted(closes.get(c, {}))
            if not days:
                continue
            a, b = bt.exright_affine(days, actions.get(c, {}))
            q = np.array([a[i] * closes[c][d] + b[i] for i, d in enumerate(days)])
            lo = np.array([a[i] * lows.get(c, {}).get(d, closes[c][d]) + b[i] for i, d in enumerate(days)])
            self.s[c] = (days, q, lo, np.array(b))

    def index(self, c, day):
        days = self.s[c][0]
        import bisect
        i = bisect.bisect_right(days, day) - 1
        return i if i >= 0 else None


def ma(q, i, n):
    return float(q[i - n + 1:i + 1].mean()) if i >= n - 1 else None


def features(P, e):
    c = e['code']
    if c not in P.s:
        return None
    days, q, lo, bb = P.s[c]
    i = P.index(c, e['date'])
    if i is None or i < 250:
        return None
    # 比较（均线、新低、跌破）在同一口径下不变；比值（回报、回撤）折到入选日口径算，避免远期前复权价为负
    x = lambda j: (q[j] - bb[i]) / (q[i] - bb[i])
    m20, m60, m250 = ma(q, i, 20), ma(q, i, 60), ma(q, i, 250)
    lows20 = [lo[j] <= lo[max(0, j - 19):j + 1].min() + 1e-12 for j in range(i - 59, i + 1)]
    feat = dict(T1=m20 > m60, T2=q[i] >= m250, T3=1.0 / max(x(j) for j in range(i - 249, i + 1)) - 1, T4=1.0 / x(i - 250) - 1,
                T5=int(sum(lows20)))
    feat.update(A1=q[i] < m250, A2=feat['T4'] < -0.30, A3=m20 <= m60)
    end = min(len(days) - 1, i + HORIZON)
    feat['hold'] = x(end) - 1
    for name, kind, n in (('S1', 'low', 20), ('S2', 'low', 60), ('S3', 'uw', 126), ('S4', 'uw', 252)):
        hit = None
        if kind == 'low':
            mark, released = lo[i - n + 1:i + 1].min(), False
            for j in range(i + 1, end + 1):
                a20, a60 = ma(q, j - 1, 20), ma(q, j - 1, 60)          # 信号日（前一日）均线判解除，与引擎同序
                if a20 is not None and a60 is not None and a20 > a60:
                    released = True
                    break
                if q[j] < mark:
                    hit = j
                    break
        else:
            streak = 0
            for j in range(i + 1, end + 1):
                streak = streak + 1 if q[j] < q[i] else 0
                if streak >= n:
                    hit = j
                    break
        feat[name] = hit is not None
        feat[f'{name}_day'] = days[hit] if hit is not None else ''
        feat[f'{name}_ret'] = x(hit) - 1 if hit is not None else None
        feat[f'{name}_after'] = x(end) / x(hit) - 1 if hit is not None else None    # 触发后至持满的回报（事后诊断，非预登记）
    return feat


def boot_diff(eps, flag, rng):
    """标记组与未标记组超额均值之差；按股票整簇自助。"""
    codes = sorted({e['code'] for e in eps})
    idx = {c: k for k, c in enumerate(codes)}
    s = np.array([idx[e['code']] for e in eps])
    x = np.array([e['excess'] for e in eps])
    f = np.array([bool(flag(e)) for e in eps])
    if f.all() or (~f).all():
        return None
    point = float(x[f].mean() - x[~f].mean())
    draws = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s]
        a, b = w * f, w * ~f
        if a.sum() > 0 and b.sum() > 0:
            draws.append(float((w * x * f).sum() / a.sum() - (w * x * ~f).sum() / b.sum()))
    return dict(diff=point, ci=[float(np.percentile(draws, 5)), float(np.percentile(draws, 95))])


RULES = (('R1', '封顶后出区', lambda e: e['pv_R1'] is not None and e['pv_R1'] > LINE),
         ('R2', '账面增长型（PR > 0.7）', lambda e: e['pr'] is not None and e['pr'] > 0.7),
         ('A1', '收盘 < MA250', lambda e: e['A1']), ('A2', '250 日回报 < −30%', lambda e: e['A2']), ('A3', 'MA20 ≤ MA60', lambda e: e['A3']),
         ('S1', '前低 20 日止损触发', lambda e: e['S1']), ('S2', '前低 60 日止损触发', lambda e: e['S2']),
         ('S3', '水下 126 日触发', lambda e: e['S3']), ('S4', '水下 252 日触发', lambda e: e['S4']))


def main():
    rows = load_rows()
    eps = episodes(rows)
    P = Prices({e['code'] for e in eps})
    kept = []
    for e in eps:
        f = features(P, e)
        if f:
            kept.append(dict(e, **f))
    rng = np.random.default_rng(SEED)
    table = {}
    for key, label, flag in RULES:
        known = [e for e in kept if not (key == 'R2' and e['pr'] is None)]
        cnt = {g: {c: sum(1 for e in known if bool(flag(e)) == g and e['cls'] == c) for c in ('恢复', '中性', '陷阱')} for g in (True, False)}
        mean = {g: (statistics.mean([e['excess'] for e in known if bool(flag(e)) == g]) if any(bool(flag(e)) == g for e in known) else None)
                for g in (True, False)}
        table[key] = dict(label=label, n=len(known), counts={str(g): v for g, v in cnt.items()}, mean={str(g): v for g, v in mean.items()},
                          diff=boot_diff(known, flag, rng))
    # 典型股票
    best, worst, seen = [], [], set()
    for e in sorted(kept, key=lambda e: -e['excess']):
        if e['code'] not in seen and len(best) < 6:
            best.append(e); seen.add(e['code'])
    for e in sorted(kept, key=lambda e: e['excess']):
        if e['code'] not in seen and len(worst) < 6:
            worst.append(e); seen.add(e['code'])
    typical = best + worst
    for code, year in FIXED:
        if code not in {e['code'] for e in typical}:
            e = next((e for e in kept if e['code'] == code and e['first'][:4] <= year <= e['last'][:4]), None)
            if e:
                typical.append(e)
    tv = {}
    for key, _label, flag in RULES:
        traps = [e for e in typical if e['cls'] == '陷阱']
        recs = [e for e in typical if e['cls'] == '恢复']
        tv[key] = dict(traps_flagged=sum(bool(flag(e)) for e in traps), traps=len(traps),
                       recs_kept=sum(not bool(flag(e)) for e in recs), recs=len(recs))
    after = {}
    for key in ('S1', 'S2', 'S3', 'S4'):
        xs = [e[f'{key}_after'] for e in kept if e[key]]
        after[key] = dict(n=len(xs), median=statistics.median(xs) if xs else None, positive=sum(v > 0 for v in xs) / len(xs) if xs else None)
    verdict = {}
    for key, _label, _flag in RULES:
        d = table[key]['diff']
        ok_all = d is not None and d['ci'][1] < 0
        t = tv[key]
        ok_typ = t['traps'] and t['traps_flagged'] * 2 >= t['traps'] and t['recs'] and t['recs_kept'] * 3 >= 2 * t['recs']
        verdict[key] = '登记为正式候选' if ok_all and ok_typ else '不满足'
    fields = ['code', 'name', 'first', 'last', 'month', 'date', 'pv', 'v', 'F1', 'pr', 'br', 'pv_R1', 'T1', 'T2', 'T3', 'T4', 'T5', 'A1', 'A2', 'A3',
              'S1', 'S1_day', 'S1_ret', 'S1_after', 'S2', 'S2_day', 'S2_ret', 'S2_after', 'S3', 'S3_day', 'S3_ret', 'S3_after',
              'S4', 'S4_day', 'S4_ret', 'S4_after', 'hold', 'f3', 'excess', 'cls']
    with (EXP / 'episodes.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(kept)
    res = dict(sample_rows=len(rows), episodes=len(eps), with_prices=len(kept), classes={c: sum(e['cls'] == c for e in kept) for c in ('恢复', '中性', '陷阱')},
               table=table, typical=[{k: e[k] for k in fields if k in e} for e in typical], typical_vote=tv, verdict=verdict, after_trigger=after)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    pct = lambda x, d=0: '—' if x is None else f'{x * 100:.{d}f}%'
    yn = lambda b: '是' if b else ''
    md = ['# OI-246 读数：谷底守卫典型股票的识别、规避买入与止损', '',
          f"样本同 OI-245 第二、三段（{len(rows)} 行）。谷底段 {len(eps)} 个，有行情特征的 {len(kept)} 个："
          + '、'.join(f"{c} {n}" for c, n in res['classes'].items()) + '（入选月 3 年年化回报减同月中位，±5pp 分界）。', '',
          '## 一、典型股票', '',
          '| 代码 | 名称 | 入选月 | `P/V` | v | F1 | PR | BR | R1 后 `P/V` | MA20>MA60 | ≥MA250 | 距 250 日高 | 250 日回报 | 近 60 日新低次数 | '
          'S1 | S2 | S3 | S4 | 3 年持有 | 超额 | 结局 |',
          '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | ---: | ---: | --- |']
    f2 = lambda v: '—' if v is None else f'{v:.2f}'
    for e in typical:
        stops = [f"{e[s + '_day']}（{pct(e[s + '_ret'])}）" if e[s] else '' for s in ('S1', 'S2', 'S3', 'S4')]
        md.append(f"| {e['code']} | {e['name']} | {e['month']} | {e['pv']:.2f} | {e['v']:.2f} | {f2(e['F1'])} | {f2(e['pr'])} | {f2(e['br'])} | "
                  f"{f2(e['pv_R1'])} | {yn(e['T1'])} | {yn(e['T2'])} | {pct(e['T3'])} | {pct(e['T4'])} | {e['T5']} | " + ' | '.join(stops)
                  + f" | {pct(e['hold'])} | {e['excess'] * 100:+.1f}pp | {e['cls']} |")
    md += ['', '## 二、全部谷底段的列联表（标记组 − 未标记组超额均值，按股票整簇自助 90%）', '',
           '| 规则 | 标记含义 | 段数 | 标记：恢复／中性／陷阱 | 未标记：恢复／中性／陷阱 | 标记组超额均值 | 未标记组 | 差 | 90% 区间 | 典型：陷阱被标记 | 典型：恢复未被标记 | 判定 |',
           '| --- | --- | ---: | --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |']
    for key, label, _flag in RULES:
        t, v = table[key], tv[key]
        c1, c0 = t['counts']['True'], t['counts']['False']
        d = t['diff']
        md.append(f"| {key} | {label} | {t['n']} | {c1['恢复']}／{c1['中性']}／{c1['陷阱']} | {c0['恢复']}／{c0['中性']}／{c0['陷阱']} | "
                  f"{pct(t['mean']['True'], 1)} | {pct(t['mean']['False'], 1)} | {pct(d['diff'], 1) if d else '—'} | "
                  f"{'[' + pct(d['ci'][0], 1) + ', ' + pct(d['ci'][1], 1) + ']' if d else '—'} | {v['traps_flagged']}/{v['traps']} | "
                  f"{v['recs_kept']}/{v['recs']} | {verdict[key]} |")
    md += ['', '## 三、事后诊断（非预登记）：触发后至持满 3 年的名义回报', '',
           '止损类规则的列联表把触发前的下跌也算进了结局，差值部分是机械的；这里只看触发之后还剩多少回报。', '',
           '| 规则 | 触发段数 | 触发后回报中位 | 触发后为正占比 |', '| --- | ---: | ---: | ---: |']
    for key in ('S1', 'S2', 'S3', 'S4'):
        a = after[key]
        md.append(f"| {key} | {a['n']} | {pct(a['median'], 1)} | {pct(a['positive'])} |")
    (EXP / 'readings.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
