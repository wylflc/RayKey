"""OI-207 混合候选（preregister_hybrids.md）：H1 利差尺度校正、H2 股利尺度 × DDM 排序、H3 参照。

    python3 hybrids.py      # 读 observations.csv（bank_methods.py analyze 的产物）→ hybrids.json
"""
import bisect
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

import bank_methods as bm

EXP = Path(__file__).resolve().parent
TRAIN_END = '2016-12'
RP_GRID = [round(0.02 + 0.0025 * i, 4) for i in range(25)]      # 2%～8%


def load_rows():
    rows = []
    with (EXP / 'observations.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            for k in ('D0', 'D1', 'E0', 'RI10', 'RIP', 'DDM10', 'DDMP', 'PBP', 'PBH', 'f1', 'f2', 'f3'):
                r[k] = float(r[k]) if r[k] not in ('', 'None') else None
            r['insurer'] = r['insurer'] == 'True'
            r['panel'] = r['panel'] == 'True'
            rows.append(r)
    return rows


def add_h1(rows, rp, key='H1'):
    rfd, rfv = bm.rf_series()
    for r in rows:
        i = bisect.bisect_right(rfd, r['date']) - 1
        rf = rfv[i] if i >= 0 else None
        r[key] = r['D0'] * (rf + rp) / (rf + 0.02) if r['D0'] and rf is not None else None


def add_rank_blend(rows, level_key, out_key):
    by = defaultdict(list)
    for r in rows:
        if not r['insurer'] and r[level_key] and r['DDM10']:
            by[r['month']].append(r)
    for r in rows:
        r[out_key] = None
    for month, rs in by.items():
        lvl = sum(math.log(r[level_key]) for r in rs) / len(rs)
        ddm = sum(math.log(r['DDM10']) for r in rs) / len(rs)
        for r in rs:
            r[out_key] = math.exp(lvl + math.log(r['DDM10']) - ddm)


def nonfin():
    src = bm.ROOT / 'data/experiments/exp_oi205b_20260928/cache/fairness_observations.csv'
    out = []
    with src.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            try:
                pv, f3 = float(r['pv_C']), float(r['f3'])
            except ValueError:
                continue
            if pv > 0:
                out.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=pv, f3=f3))
    return out


def offset(rows, nf, key, universe='面板', lo='0000-00', hi='9999-99', boot=1000, seed=20260928):
    """与非金融同尺的银行偏差 c（月效应，共同斜率），按股票整簇自助 90% 区间。"""
    rng = np.random.default_rng(seed)
    base = [r for r in nf if (r['panel'] or universe == '全部') and lo <= r['month'] <= hi and 0.2 <= r['pv'] <= 5]
    banks = [dict(code=r['code'], month=r['month'], pv=r[key], f3=r['f3']) for r in rows
             if not r['insurer'] and r[key] and r['f3'] is not None and (r['panel'] or universe == '全部')
             and lo <= r['month'] <= hi and 0.2 <= r[key] <= 5]
    sample = [dict(r, bank=0.0) for r in base] + [dict(r, bank=1.0) for r in banks]
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    y = np.log1p(np.array([r['f3'] for r in sample])); x = np.log(np.array([r['pv'] for r in sample]))
    z = np.array([r['bank'] for r in sample]); t = np.array([months[r['month']] for r in sample]); s = np.array([codes[r['code']] for r in sample])

    def fit(w):
        tot = np.bincount(t, weights=w); safe = np.where(tot > 0, tot, 1.0)
        cols = [c - (np.bincount(t, weights=w * c) / safe)[t] for c in (y, x, z)]
        X = np.column_stack(cols[1:]); Xw = X * w[:, None]
        return np.linalg.solve(X.T @ Xw, Xw.T @ cols[0])
    beta = fit(np.ones(len(y)))
    draws = [fit(np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s])[1] for _ in range(boot)]
    pv = np.array([r['pv'] for r in banks])
    return dict(n_banks=len(banks), c=float(beta[1]), c_ci=[float(np.percentile(draws, 5)), float(np.percentile(draws, 95))],
                b=float(beta[0]), bank_pv_median=float(np.median(pv)) if len(pv) else None,
                bank_zone_share=float((pv <= bm.LINE).mean()) if len(pv) else None)


def main():
    rows = load_rows()
    nf = nonfin()
    scan = []
    for rp in RP_GRID:
        add_h1(rows, rp, key='_H1')
        e = offset(rows, nf, '_H1', lo='0000-00', hi=TRAIN_END, boot=1)   # 只取点估计
        scan.append(dict(rp=rp, c=e['c']))
    rp_star = min(scan, key=lambda x: abs(x['c']))['rp']
    add_h1(rows, rp_star)
    add_rank_blend(rows, 'D0', 'H2')
    add_rank_blend(rows, 'H1', 'H3')
    methods = ('D0', 'DDM10', 'H1', 'H2', 'H3')
    bm.METHODS = methods
    out = dict(rp_scan=scan, rp_star=rp_star, R1=bm.r1(rows), R3=bm.r3(rows), R4=bm.r4(rows), R2={})
    for universe in ('面板', '全部'):
        for label, lo, hi in (('全样本', '0000-00', '9999-99'), ('训练段 ≤2016', '0000-00', TRAIN_END), ('样本外 2017 起', '2017-01', '9999-99')):
            for m in methods:
                out['R2'][f'{universe}:{label}:{m}'] = offset(rows, nf, m, universe, lo, hi)
    latest = max(r['month'] for r in rows)
    out['current'] = {r['name']: {m: r.get(m) for m in methods} for r in rows if r['month'] == latest}
    out['current_month'] = latest
    (EXP / 'hybrids.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float) + '\n')
    print('RP*', rp_star)
    for k, v in out['R2'].items():
        print(k, 'c %+.3f [%+.3f, %+.3f] n %d med %.2f zone %.2f' % (v['c'], v['c_ci'][0], v['c_ci'][1], v['n_banks'], v['bank_pv_median'] or 0, v['bank_zone_share'] or 0))
    for h in ('1y', '3y'):
        print(h, {m: round(v['mean_ic'], 3) for m, v in out['R1'][h].items()})
    for m in methods:
        v = out['R4'][m]
        print('R4', m, {k: round(v[k]['point'], 3) for k in ('zone_share', 'opp_capture', 'lift_opp', 'lift_trap')})


if __name__ == '__main__':
    main()
