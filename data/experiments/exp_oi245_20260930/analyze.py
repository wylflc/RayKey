"""OI-245 读数（preregister.md 第 1～5 条与判据）。

回归同 OI-227／OI-244：`log(1 + f_h) = a_月 + b·log(P/V) + Σ c_j·D_j`，月效应组内去均值，按股票整簇自助 1000 次，区间 90%。

    python3 analyze.py     # → readings.json、readings.md、cases.csv
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

import observations as obs

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PV_RANGE, BOOT, SEED = (0.2, 5.0), 1000, 20260930
SIGNAL = '2026-09-30'
HOLDINGS = {'000651': '格力电器', '603529': '爱玛科技', '600036': '招商银行', '601318': '中国平安', '601717': '中创智领', '920599': '同力股份'}
PERIODS = (('2007–2013', '2007-01', '2013-12'), ('2014–2019', '2014-01', '2019-12'), ('2020 年起', '2020-01', '9999-12'))
FEATURES = (('F1', 'F1 盈利基数位置'), ('F2', 'F2 增长腿占比'), ('F3', 'F3 净现金占比'))


def fnum(v):
    return None if v in ('', 'None', None) else float(v)


def load():
    rows = []
    with (EXP / 'observations.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            rows.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']), f3r=fnum(r['f3']),
                             f5r=fnum(r['f5']), F1=fnum(r['F1']), cyc=fnum(r['cyc']), F2=fnum(r['F2']), wc=fnum(r['wc_absorb']),
                             F3=fnum(r['F3']), path=r['path']))
    return rows


def fit(y, x, D, t, w):
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    dm = lambda c: c - (np.bincount(t, weights=w * c) / safe)[t]
    X = np.column_stack([dm(x)] + [dm(D[:, j]) for j in range(D.shape[1])])
    Xw = X * w[:, None]
    beta = np.linalg.solve(X.T @ Xw, Xw.T @ dm(y))
    return float(beta[0]), beta[1:]


def regress(rows, h, cols, names, rng, panel_only=True, since='2007-01', until='9999-12'):
    sample = [r for r in rows if (r['panel'] or not panel_only) and since <= r['month'] <= until and r[f'f{h}r'] is not None
              and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1] and all(fn(r) is not None for fn in cols)]
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    t = np.array([months[r['month']] for r in sample])
    s = np.array([codes[r['code']] for r in sample])
    y = np.log1p(np.array([r[f'f{h}r'] for r in sample]))
    x = np.log(np.array([r['pv'] for r in sample]))
    D = np.column_stack([[float(fn(r)) for r in sample] for fn in cols])
    b, c = fit(y, x, D, t, np.ones(len(y)))
    draws_b, draws_c = [], []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s]
        try:
            bb, cc = fit(y, x, D, t, w)
        except np.linalg.LinAlgError:
            continue
        draws_b.append(bb); draws_c.append(cc)
    draws_b, draws_c = np.array(draws_b), np.array(draws_c)
    q = lambda v: [float(np.percentile(v, 5)), float(np.percentile(v, 95))]
    out = dict(n=len(sample), codes=len(codes), months=len(months), b=b, b_ci=q(draws_b), draws=len(draws_b))
    for j, name in enumerate(names):
        cj = float(c[j])
        vals = D[:, j]
        out[name] = dict(c=cj, c_ci=q(draws_c[:, j]), mean=float(vals.mean()), p10=float(np.percentile(vals, 10)),
                         p90=float(np.percentile(vals, 90)))
    return out


def add_quintiles(rows, key):
    """每月在册截面（该特征非空、样本 ≥ 10）按特征排序，最高五分之一记 1，其余 0。"""
    by = defaultdict(list)
    for r in rows:
        if r['panel'] and r[key] is not None and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]:
            by[r['month']].append(r)
    for r in rows:
        r[f'q_{key}'] = None
    for month, rs in by.items():
        if len(rs) < 10:
            continue
        rs.sort(key=lambda r: r[key])
        n = len(rs)
        for i, r in enumerate(rs):
            r[f'q_{key}'] = 1.0 if i >= math.ceil(0.8 * n) else 0.0


def verdict(main, quint):
    lo, hi = main['c_ci']
    if lo <= 0 <= hi:
        return '不支持'
    if hi < 0:
        qlo, qhi = quint['c_ci']
        return '支持' if qhi < 0 else '主读数为负，分位不显著（未达支持）'
    return '相反'


def cases(fits):
    """现行池按最新带（可得日 ≤ 09-30、状态 ok）列三项特征；主读数支持的来源附示意折算。"""
    with (ROOT / 'data/processed/daily_buy_candidates.csv').open(newline='', encoding='utf-8') as f:
        cand = {r['security_code']: r for r in csv.DictReader(f)}
    codes = set(cand)
    latest = {}
    with obs.BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = r['security_code']
            if c in codes and r['status'] == 'ok' and len(r['available_at']) == 10 and r['available_at'] <= SIGNAL:
                if c not in latest or (r['available_at'], r['report_date']) > (latest[c]['available_at'], latest[c]['report_date']):
                    latest[c] = r
    _rows, annual = obs.load_bands(codes)
    out = []
    for c, band in sorted(latest.items()):
        if band['roic_path'] not in obs.PATHS:
            continue
        feat = obs.features(band, annual.get(c, []), band['report_date'], band['available_at'])
        row = dict(code=c, name=cand[c].get('security_name', ''), pv=fnum(cand[c].get('model_pv')), path=band['roic_path'],
                   mode=band['roic_nopat_mode'], F1=feat['F1'], cyc=feat['cyc'], F2=feat['F2'], wc_absorb=feat['wc_absorb'],
                   F3=feat['F3'], holding=c in HOLDINGS)
        factor = 1.0
        for key, _label in FEATURES:
            e = fits.get(key)
            if e and e['verdict'] == '支持' and row[key] is not None:
                factor *= math.exp(-e['c'] * row[key] / e['b'])
        row['illustrative_v_factor'] = factor
        row['illustrative_pv'] = row['pv'] / factor if row['pv'] else None
        out.append(row)
    with (EXP / 'cases.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    return out


def main():
    rows = load()
    for r in rows:
        r['f1c'] = r['F1'] * r['cyc'] if r['F1'] is not None and r['cyc'] is not None else None
        r['f1n'] = r['F1'] * (1 - r['cyc']) if r['F1'] is not None and r['cyc'] is not None else None
        r['f2wc'] = r['F2'] * r['wc'] if r['F2'] is not None and r['wc'] is not None else None
    col = {k: (lambda r, k=k: r[k]) for k, _ in FEATURES}
    for key, _label in FEATURES:
        add_quintiles(rows, key)
    rng = np.random.default_rng(SEED)
    res = dict(main={}, quintile={}, joint=None, interaction={}, robust={}, fits={})
    for key, label in FEATURES:
        main = regress(rows, 3, [col[key]], [key], rng)
        quint = regress(rows, 3, [lambda r, qk='q_' + key: r[qk]], [key], rng)
        res['main'][key] = main
        res['quintile'][key] = quint
        res['fits'][key] = dict(c=main[key]['c'], b=main['b'], verdict=verdict(main[key], quint[key]))
        rob = {'5 年': regress(rows, 5, [col[key]], [key], rng),
               '全部样本': regress(rows, 3, [col[key]], [key], rng, panel_only=False)}
        for label_p, a, z in PERIODS:
            rob[label_p] = regress(rows, 3, [col[key]], [key], rng, since=a, until=z)
        res['robust'][key] = rob
        print(label, res['fits'][key], flush=True)
    res['joint'] = regress(rows, 3, [col['F1'], col['F2'], col['F3']], ['F1', 'F2', 'F3'], rng)
    res['interaction']['f1_cyc'] = regress(rows, 3, [lambda r: r['cyc'], lambda r: r['f1c'], lambda r: r['f1n']],
                                           ['cyc', 'f1_cyclical', 'f1_noncyclical'], rng)
    res['interaction']['f2_wc'] = regress(rows, 3, [col['F2'], lambda r: r['wc'], lambda r: r['f2wc']], ['F2', 'wc_absorb', 'f2_x_wc'], rng)
    res['cases'] = cases(res['fits'])
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    write_md(res)


def write_md(res):
    pp = lambda v: f'{v * 100:+.2f}'
    ci = lambda v: f'[{v[0] * 100:+.2f}, {v[1] * 100:+.2f}]'
    out = ['# OI-245 读数：非金融增长路径三处偏乐观来源（全池股票月份）', '',
           'c = 同 `P/V` 下特征每增加 1 单位，其后 3 年年化对数回报的变化（pp；负 = 模型对该特征偏乐观）。'
           '区间为按股票整簇自助 1000 次的 90% 区间。主读数：面板在册、3 年、起始月 2007-01 起。', '',
           '## 一、主读数与分位', '',
           '| 特征 | 观测／家 | 特征 P10～P90 | b | c（pp） | c 区间 | 最高五分之一 c | 区间 | 判定 |',
           '| --- | ---: | --- | ---: | ---: | --- | ---: | --- | --- |']
    for key, label in FEATURES:
        m, q = res['main'][key], res['quintile'][key]
        out.append(f"| {label} | {m['n']}／{m['codes']} | {m[key]['p10']:.2f}～{m[key]['p90']:.2f} | {m['b']:.3f} | {pp(m[key]['c'])} | "
                   f"{ci(m[key]['c_ci'])} | {pp(q[key]['c'])} | {ci(q[key]['c_ci'])} | {res['fits'][key]['verdict']} |")
    j = res['joint']
    out += ['', f"联合回归（{j['n']} 行）：" + '；'.join(f"{label} {pp(j[k]['c'])} {ci(j[k]['c_ci'])}" for k, label in FEATURES) + '。', '',
            '## 二、交互', '']
    a = res['interaction']['f1_cyc']
    out.append(f"F1 × 周期（{a['n']} 行）：周期组 {pp(a['f1_cyclical']['c'])} {ci(a['f1_cyclical']['c_ci'])}；"
               f"非周期组 {pp(a['f1_noncyclical']['c'])} {ci(a['f1_noncyclical']['c_ci'])}；周期虚拟变量 {pp(a['cyc']['c'])} {ci(a['cyc']['c_ci'])}。")
    a = res['interaction']['f2_wc']
    out.append(f"F2 × 营运资金吸收（{a['n']} 行）：F2 {pp(a['F2']['c'])} {ci(a['F2']['c_ci'])}；吸收 {pp(a['wc_absorb']['c'])} {ci(a['wc_absorb']['c_ci'])}；"
               f"乘积 {pp(a['f2_x_wc']['c'])} {ci(a['f2_x_wc']['c_ci'])}。")
    out += ['', '## 三、稳健性', '', '| 特征 | 口径 | 观测 | c（pp） | c 区间 |', '| --- | --- | ---: | ---: | --- |']
    for key, label in FEATURES:
        for name, e in res['robust'][key].items():
            out.append(f"| {label} | {name} | {e['n']} | {pp(e[key]['c'])} | {ci(e[key]['c_ci'])} |")
    out += ['', '## 四、现行池个案（最新带；六只持仓与各特征最高 10 只）', '',
            '| 代码 | 名称 | 持仓 | `P/V` | F1 | 周期 | F2 | 营运资金吸收 | F3 | 示意 V 系数 | 示意 `P/V` |',
            '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    f = lambda v: '' if v is None else f'{v:.2f}'
    picks = {r['code'] for r in res['cases'] if r['holding']}
    for key, _label in FEATURES:
        picks |= {r['code'] for r in sorted((r for r in res['cases'] if r[key] is not None), key=lambda r: -r[key])[:10]}
    for r in sorted((r for r in res['cases'] if r['code'] in picks), key=lambda r: (not r['holding'], r['pv'] or 9)):
        out.append(f"| {r['code']} | {r['name']} | {'是' if r['holding'] else ''} | {f(r['pv'])} | {f(r['F1'])} | {'' if r['cyc'] is None else int(r['cyc'])} | "
                   f"{f(r['F2'])} | {f(r['wc_absorb'])} | {f(r['F3'])} | {r['illustrative_v_factor']:.3f} | {f(r['illustrative_pv'])} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
