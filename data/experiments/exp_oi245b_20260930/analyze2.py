"""OI-245 第二段读数（preregister.md 一、二与判据）。

主式同第一段：`log(1 + f3) = a_月 + b·log(P/V) + Σ c·D`，面板在册、3 年、2007 年起，按股票整簇自助 1000 次，区间 90%。
公允性 λ 同 OI-213／OI-217：`log(1 + f3) = a_月 + b·x + g·d`，`d = log(P/V') − log(P/V)`，`λ = g ÷ b`。

    python3 analyze2.py     # → readings2.json、readings2.md、cases2.csv
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

import observations2 as ob

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PV_RANGE, BOOT, SEED, LINE = (0.2, 5.0), 1000, 20260930, 1.0034
SIGNAL = '2026-09-30'
HOLDINGS = ('000651', '603529', '601717', '920599')
PERIODS = (('2007–2013', '2007-01', '2013-12'), ('2014–2019', '2014-01', '2019-12'), ('2020 年起', '2020-01', '9999-12'))
NAMES = [name for name, *_ in ob.CANDIDATES]


def fnum(v):
    return None if v in ('', 'None', None) else float(v)


def load():
    rows = []
    with (EXP / 'observations2.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            row = dict(code=r['code'], name=r['name'], gate=r['gate'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']),
                       y=fnum(r['f3']), path=r['path'], lam=fnum(r['lam']), w=fnum(r['w']) or 0.0, v=fnum(r['v']) or 0.0,
                       F1=fnum(r['F1']), rec=fnum(r['f1_recent']), old=fnum(r['f1_old']))
            for n in NAMES:
                row[n] = fnum(r[f'pv_{n}'])
            rows.append(row)
    return [r for r in rows if r['panel'] and r['y'] is not None and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]]


def fit(y, X, t, w):
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    dm = lambda c: c - (np.bincount(t, weights=w * c) / safe)[t]
    Xd = np.column_stack([dm(X[:, j]) for j in range(X.shape[1])])
    Xw = Xd * w[:, None]
    return np.linalg.solve(Xd.T @ Xw, Xw.T @ dm(y))


def design(sample, cols):
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    t = np.array([months[r['month']] for r in sample])
    s = np.array([codes[r['code']] for r in sample])
    y = np.log1p(np.array([r['y'] for r in sample]))
    X = np.column_stack([np.array([float(fn(r)) for r in sample]) for fn in cols])
    return y, X, t, s, len(codes)


def regress(rows, cols, names, rng, since='2007-01', until='9999-12', keep=lambda r: True, boot=BOOT):
    """cols[0] 恒为 log(P/V)（或 log(P/V')）；报 b 与其余各列的 c。"""
    sample = [r for r in rows if since <= r['month'] <= until and keep(r) and all(fn(r) is not None for fn in cols)]
    if len({r['code'] for r in sample}) < 10:
        return dict(n=len(sample), skipped=True)
    y, X, t, s, n_codes = design(sample, cols)
    beta = fit(y, X, t, np.ones(len(y)))
    draws = []
    for _ in range(boot):
        w = np.bincount(rng.integers(0, n_codes, n_codes), minlength=n_codes).astype(float)[s]
        try:
            draws.append(fit(y, X, t, w))
        except np.linalg.LinAlgError:
            continue
    d = np.array(draws)
    q = lambda v: [float(np.nanpercentile(v, 5)), float(np.nanpercentile(v, 95))]
    out = dict(n=len(sample), codes=n_codes, b=float(beta[0]), b_ci=q(d[:, 0]))
    for j, name in enumerate(names, start=1):
        out[name] = dict(c=float(beta[j]), c_ci=q(d[:, j]))
    out['_draws'] = d
    return out


def lam_verdict(ci):
    lo, hi = ci
    has0, has1 = lo <= 0 <= hi, lo <= 1 <= hi
    if has1 and not has0:
        return '数据支持该调整'
    if has0 and not has1:
        return '不支持，现口径更准'
    if not has0 and not has1:
        return '按点估计报比例'
    return '不能区分'


def fairness(rows, name, rng, since='2007-01', until='9999-12'):
    x = lambda r: math.log(r['pv'])
    d = lambda r: math.log(r[name]) - math.log(r['pv']) if r[name] else None
    e = regress(rows, [x, d], ['d'], rng, since, until)
    if e.get('skipped'):
        return e
    draws = e.pop('_draws')
    lam = draws[:, 1] / draws[:, 0]
    ci = [float(np.nanpercentile(lam, 5)), float(np.nanpercentile(lam, 95))]
    sample = [r for r in rows if since <= r['month'] <= until and r[name] is not None]
    moved = [r for r in sample if abs(math.log(r[name]) - math.log(r['pv'])) > 1e-9]
    return dict(n=e['n'], codes=e['codes'], b=e['b'], g=e['d']['c'], lam=e['d']['c'] / e['b'], lam_ci=ci, verdict=lam_verdict(ci),
                moved=len(moved), moved_codes=len({r['code'] for r in moved}),
                mean_d=float(np.mean([math.log(r[name]) - math.log(r['pv']) for r in moved])) if moved else None)


def strip(e):
    return {k: v for k, v in e.items() if k != '_draws'}


def diagnostics(rows, rng):
    x = lambda r: math.log(r['pv'])
    f1 = lambda r: r['F1']
    out = {}
    groups = {'w > 0（周期守卫）': lambda r: r['w'] > 0, 'v > 0（谷底守卫）': lambda r: r['v'] > 0,
              'λ = 0（w = v = 0）': lambda r: r['w'] == 0 and r['v'] == 0 and r['lam'] == 0,
              'λ = ½（w = v = 0）': lambda r: r['w'] == 0 and r['v'] == 0 and r['lam'] == 0.5,
              'λ = 1（w = v = 0）': lambda r: r['w'] == 0 and r['v'] == 0 and r['lam'] == 1}
    out['groups'] = {k: strip(regress(rows, [x, f1], ['F1'], rng, keep=fn)) for k, fn in groups.items()}
    out['decomposition'] = strip(regress(rows, [x, lambda r: r['rec'], lambda r: r['old']], ['近因', '旧因'], rng))
    paths = {'growth 路径': lambda r: r['path'] == 'growth', 'zero_growth 路径': lambda r: r['path'] == 'zero_growth',
             '制造业 C': lambda r: r['gate'] == 'C', '其余门类': lambda r: r['gate'] != 'C'}
    out['paths'] = {k: strip(regress(rows, [x, f1], ['F1'], rng, keep=fn)) for k, fn in paths.items()}
    out['subperiods'] = {'2020–2021': strip(regress(rows, [x, f1], ['F1'], rng, '2020-01', '2021-12')),
                         '2022 年起': strip(regress(rows, [x, f1], ['F1'], rng, '2022-01'))}
    # 集中度：逐只剔除（不重抽）与高 F1 行的残差贡献
    sample = [r for r in rows if r['F1'] is not None]
    y, X, t, s, n_codes = design(sample, [x, f1])
    codes = sorted({r['code'] for r in sample})
    loo = []
    for i, c in enumerate(codes):
        w = (s != i).astype(float)
        beta = fit(y, X, t, w)
        loo.append((float(beta[1]), c))
    loo.sort()
    base_beta = fit(y, X[:, :1], t, np.ones(len(y)))
    tot = np.bincount(t)
    dm = lambda c: c - (np.bincount(t, weights=c) / tot)[t]
    resid = dm(y) - base_beta[0] * dm(X[:, 0])
    contrib = defaultdict(lambda: [0, 0.0, 0.0])
    for i, r in enumerate(sample):
        if r['F1'] >= 0.4:
            e = contrib[(r['code'], r['name'])]
            e[0] += 1; e[1] += float(resid[i]); e[2] += r['F1']
    top = sorted(contrib.items(), key=lambda kv: kv[1][1])[:10]
    out['concentration'] = dict(loo_min=loo[0], loo_max=loo[-1],
                                top=[dict(code=c, name=n, rows=v[0], resid_sum=v[1], resid_mean=v[1] / v[0], mean_F1=v[2] / v[0])
                                     for (c, n), v in top])
    return out


def zone_share(rows, key):
    xs = [r[key] for r in rows if r[key] is not None]
    return sum(v <= LINE for v in xs) / len(xs) if xs else None


def cases():
    """现行池（非金融带）最新带 × 四个候选：V、V' 与示意 `P/V'`（按带层比例折算到当日候选侧 `P/V`）。"""
    with (ROOT / 'data/processed/daily_buy_candidates.csv').open(newline='', encoding='utf-8') as f:
        cand = {r['security_code']: r for r in csv.DictReader(f)}
    latest, annual = {}, defaultdict(list)
    with ob.obs1.BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = r['security_code']
            if c not in cand or r['status'] != 'ok' or len(r['available_at']) != 10 or r['available_at'] > SIGNAL:
                continue
            if r['report_date'].endswith('-12-31'):
                nopat, shares = ob.obs1.num(r['nopat_ps']), ob.obs1.num(r['shares_est'])
                annual[c].append(dict(fy=int(r['report_date'][:4]), av=r['available_at'],
                                      nopat=nopat * shares if nopat is not None and shares else None))
            if c not in latest or (r['available_at'], r['report_date']) > (latest[c]['available_at'], latest[c]['report_date']):
                latest[c] = r
    out = []
    for c, band in latest.items():
        if band['roic_path'] not in ob.obs1.PATHS:
            continue
        nopat, shares = ob.obs1.num(band['nopat_ps']), ob.obs1.num(band['shares_est'])
        base = nopat * shares if nopat is not None and shares else None
        prior = [a['nopat'] for a in ob.obs1.history(annual[c], int(band['report_date'][:4]), band['available_at'], 5) if a['nopat'] is not None]
        m5 = statistics.median(prior) if len(prior) >= 3 else None
        v_band, nd, lam = ob.obs1.num(band['intrinsic_value']), ob.obs1.num(band['net_debt_ps']) or 0.0, ob.obs1.num(band['growth_trust'])
        pv = fnum(cand[c].get('model_pv'))
        row = dict(code=c, name=cand[c].get('security_name', ''), holding=c in HOLDINGS, pv=pv, v=v_band, ratio=base / m5 if base and m5 else None,
                   lam=lam, mode=band['roic_nopat_mode'])
        for name, t, only in ob.CANDIDATES:
            w, base2 = ob.guard(base, m5, lam, t, only)
            v2 = (v_band + nd) * base2 / base - nd if w > 0 else v_band
            row[f'v_{name}'] = v2
            row[f'pv_{name}'] = pv * v_band / v2 if pv and v2 and v2 > 0 else None
        out.append(row)
    with (EXP / 'cases2.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    return out


def main():
    rows = load()
    rng = np.random.default_rng(SEED)
    res = dict(sample=len(rows), diagnostics=diagnostics(rows, rng), candidates={})
    x = lambda r: math.log(r['pv'])
    for name in NAMES:
        e = dict(main=fairness(rows, name, rng))
        e['periods'] = {label: fairness(rows, name, rng, a, z) for label, a, z in PERIODS}
        e['residual_F1'] = strip(regress(rows, [lambda r, n=name: math.log(r[n]) if r[n] else None, lambda r: r['F1']], ['F1'], rng))
        e['zone'] = dict(current=zone_share(rows, 'pv'), candidate=zone_share(rows, name))
        res['candidates'][name] = e
        print(name, e['main'], flush=True)
    res['main_verdict'] = res['candidates']['LG1.3']['main']['verdict']
    res['cases'] = cases()
    (EXP / 'readings2.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + '\n')
    write_md(res)


def write_md(res):
    pp = lambda v: f'{v * 100:+.2f}'
    ci = lambda v: f'[{v[0] * 100:+.2f}, {v[1] * 100:+.2f}]'
    lc = lambda v: f'[{v[0]:+.2f}, {v[1]:+.2f}]'
    dg = res['diagnostics']
    out = ['# OI-245 第二段读数：利润基数高位的成因与水平守卫候选', '',
           f"样本：面板在册、3 年、`P/V` ∈ [0.2, 5] 的月末 {res['sample']} 行。c 为 pp／单位 F1，区间为按股票整簇自助 1000 次的 90% 区间。", '',
           '## 一、成因（描述）', '', '| 分组 | 行／家 | c（F1） | 区间 |', '| --- | ---: | ---: | --- |']
    for block in ('groups', 'paths', 'subperiods'):
        for k, e in dg[block].items():
            if e.get('skipped'):
                out.append(f'| {k} | {e["n"]} | — | 样本不足 |')
            else:
                out.append(f"| {k} | {e['n']}／{e['codes']} | {pp(e['F1']['c'])} | {ci(e['F1']['c_ci'])} |")
    d = dg['decomposition']
    out += ['', f"拆分（{d['n']} 行）：近因 ln(基数 ÷ 上年年报基数) {pp(d['近因']['c'])} {ci(d['近因']['c_ci'])}；"
                f"旧因 ln(上年年报基数 ÷ 5 年中位) {pp(d['旧因']['c'])} {ci(d['旧因']['c_ci'])}。"]
    cc = dg['concentration']
    out += ['', f"逐只剔除后 c 的范围：{pp(cc['loo_min'][0])}（剔除 {cc['loo_min'][1]}）～{pp(cc['loo_max'][0])}（剔除 {cc['loo_max'][1]}）。", '',
            '高 F1（≥ 0.4）行残差合计最负的 10 只：', '', '| 代码 | 名称 | 行数 | 平均 F1 | 平均残差（pp） | 残差合计 |', '| --- | --- | ---: | ---: | ---: | ---: |']
    for t in cc['top']:
        out.append(f"| {t['code']} | {t['name']} | {t['rows']} | {t['mean_F1']:.2f} | {pp(t['resid_mean'])} | {t['resid_sum']:+.2f} |")
    out += ['', '## 二、水平守卫候选（公允性 λ，主读数 LG1.3）', '',
            '| 候选 | 变动行／家 | 平均 d | λ | λ 区间 | 判定 | 2007–2013 λ | 2014–2019 λ | 2020 年起 λ | 残余 F1 c | 区间 | 区内占比 现行→候选 |',
            '| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |']
    for name, e in res['candidates'].items():
        m = e['main']
        per = [f"{e['periods'][p]['lam']:+.2f}" if not e['periods'][p].get('skipped') else '—' for p, *_ in PERIODS]
        r = e['residual_F1']
        z = e['zone']
        out.append(f"| {name} | {m['moved']}／{m['moved_codes']} | {m['mean_d']:+.3f} | {m['lam']:+.2f} | {lc(m['lam_ci'])} | {m['verdict']} | "
                   + ' | '.join(per) + f" | {pp(r['F1']['c'])} | {ci(r['F1']['c_ci'])} | {z['current']:.2%}→{z['candidate']:.2%} |")
    out += ['', f"**主读数判定（LG1.3）：{res['main_verdict']}。**", '',
            '## 三、现行池个案（模型带口径；持仓与 LG1.3 下 V 降幅最大的 10 只）', '',
            '| 代码 | 名称 | 持仓 | 基数 ÷ M5 | λ | `P/V` | V | LG1.3 V′ | `P/V′` | LG1.6 `P/V′` | LG2.0 `P/V′` | LGλ1.3 `P/V′` |',
            '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    f = lambda v: '' if v is None else f'{v:.2f}'
    rows = res['cases']
    drop = sorted((r for r in rows if r['v'] and r['v_LG1.3']), key=lambda r: r['v_LG1.3'] / r['v'])[:10]
    pick = {r['code'] for r in rows if r['holding']} | {r['code'] for r in drop}
    for r in sorted((r for r in rows if r['code'] in pick), key=lambda r: (not r['holding'], (r['v_LG1.3'] / r['v']) if r['v'] else 9)):
        out.append(f"| {r['code']} | {r['name']} | {'是' if r['holding'] else ''} | {f(r['ratio'])} | {f(r['lam'])} | {f(r['pv'])} | {f(r['v'])} | "
                   f"{f(r['v_LG1.3'])} | {f(r['pv_LG1.3'])} | {f(r['pv_LG1.6'])} | {f(r['pv_LG2.0'])} | {f(r['pv_LGλ1.3'])} |")
    (EXP / 'readings2.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
