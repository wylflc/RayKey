"""OI-244 读数（preregister.md 第 1～4 条）：银行同尺系数的分时段、分组与招商银行单列。

口径同 OI-227／OI-230：`log(1 + f_h) = a_月 + b·log(P/V) + Σ c_j·D_j`，`k = exp(−c ÷ b)`，按股票整簇自助。
银行 = `exp_oi230_20260929/bank_observations_DC_RAW.csv`（未缩放），非金融 = `exp_oi227_20260928/nonfin_v4216.csv`。

    python3 analyze.py     # → readings.json、readings.md
"""
import csv
import json
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
BANKS = ROOT / 'data/experiments/exp_oi230_20260929/bank_observations_DC_RAW.csv'
NONFIN = ROOT / 'data/experiments/exp_oi227_20260928/nonfin_v4216.csv'
PV_RANGE, BOOT, SEED = (0.2, 5.0), 1000, 20260930
CMB = '600036'
BIG6 = {'601398', '601939', '601288', '601988', '601328', '601658'}
JOINT = {'600036', '601166', '600000', '600016', '601998', '601818', '600015', '000001', '601916'}
PERIODS = [('全期', '2007-01', '9999-12'), ('2010–2013', '2010-01', '2013-12'), ('2014–2016', '2014-01', '2016-12'),
           ('2017–2019', '2017-01', '2019-12'), ('2020 年起', '2020-01', '9999-12'), ('2022 年起', '2022-01', '9999-12')]


def num(v):
    return None if v in ('', 'None', None) else float(v)


def load():
    rows = []
    for path, bank in ((NONFIN, False), (BANKS, True)):
        with path.open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                pv = num(r.get('pv'))
                if pv is None:
                    continue
                rows.append(dict(code=r['code'].zfill(6), month=r['month'], panel=r['panel'] == 'True', pv=pv, f3=num(r['f3']),
                                 f5=num(r['f5']), bank=bank))
    return rows


def design(sample, dummies):
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    return (np.array([months[r['month']] for r in sample]), np.array([codes[r['code']] for r in sample]), len(codes),
            np.column_stack([[float(fn(r)) for r in sample] for fn in dummies]) if dummies else np.zeros((len(sample), 0)))


def fit(y, x, D, t, w, b_fixed=None):
    """月效应（组内去均值）＋共同斜率 b＋虚拟变量系数；b_fixed 给定时只估虚拟变量。"""
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    dm = lambda c: c - (np.bincount(t, weights=w * c) / safe)[t]
    yc = dm(y)
    Dc = np.column_stack([dm(D[:, j]) for j in range(D.shape[1])]) if D.shape[1] else D
    if b_fixed is not None:
        yc = yc - b_fixed * dm(x)
        X = Dc
    else:
        X = np.column_stack([dm(x), Dc])
    Xw = X * w[:, None]
    beta = np.linalg.solve(X.T @ Xw, Xw.T @ yc)
    return (b_fixed, beta) if b_fixed is not None else (float(beta[0]), beta[1:])


def readout(rows, h, since, until, dummies, names, panel_only=True, b_fixed=None, rng=None):
    sample = [r for r in rows if (r['panel'] or not panel_only) and since <= r['month'] <= until and r[f'f{h}'] is not None
              and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]]
    t, s, ncode, D = design(sample, dummies)
    y = np.log1p(np.array([r[f'f{h}'] for r in sample]))
    x = np.log(np.array([r['pv'] for r in sample]))
    b, c = fit(y, x, D, t, np.ones(len(y)), b_fixed)
    draws_b, draws_c = [], []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, ncode, ncode), minlength=ncode).astype(float)[s]
        try:
            bb, cc = fit(y, x, D, t, w, b_fixed)
        except np.linalg.LinAlgError:
            continue
        draws_b.append(bb if b_fixed is None else b_fixed)
        draws_c.append(cc)
    draws_b, draws_c = np.array(draws_b), np.array(draws_c)
    q = lambda v: [float(np.percentile(v, 5)), float(np.percentile(v, 95))]
    out = dict(n=len(sample), bank_rows=int(sum(r['bank'] for r in sample)), bank_codes=len({r['code'] for r in sample if r['bank']}),
               months=len(set(r['month'] for r in sample)), b=float(b), b_ci=q(draws_b) if b_fixed is None else None)
    for j, name in enumerate(names):
        cj = float(c[j])
        k_draws = np.exp(-draws_c[:, j] / draws_b)
        out[name] = dict(c=cj, c_ci=q(draws_c[:, j]), k=float(np.exp(-cj / b)), k_ci=q(k_draws))
    if len(names) == 2:
        diff = draws_c[:, 0] - draws_c[:, 1]
        out['diff'] = dict(c=float(c[0] - c[1]), c_ci=q(diff), share_positive=float((diff > 0).mean()))
    return out


def spearman_by_month(rows, h, since, until):
    """银行内逐月截面：P/V 与前向回报的秩相关，取中位。"""
    by = {}
    for r in rows:
        if r['bank'] and r['panel'] and since <= r['month'] <= until and r[f'f{h}'] is not None and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]:
            by.setdefault(r['month'], []).append((r['pv'], r[f'f{h}']))
    rank = lambda v: np.argsort(np.argsort(v)).astype(float)
    rho = [float(np.corrcoef(rank([a for a, _ in xs]), rank([b for _, b in xs]))[0, 1]) for xs in by.values() if len(xs) >= 5]
    return dict(months=len(rho), median=float(np.median(rho)) if rho else None)


def main():
    rows = load()
    rng = np.random.default_rng(SEED)
    bank = [lambda r: r['bank']]
    res = dict(periods={}, periods_fixed_b={}, cmb={}, groups=None, robust={}, spearman={})
    full = readout(rows, 3, '2007-01', '9999-12', bank, ['bank'], rng=rng)
    b_full = full['b']
    for label, a, z in PERIODS:
        res['periods'][label] = full if label == '全期' else readout(rows, 3, a, z, bank, ['bank'], rng=rng)
        res['periods_fixed_b'][label] = readout(rows, 3, a, z, bank, ['bank'], b_fixed=b_full, rng=rng)
        res['spearman'][label] = spearman_by_month(rows, 3, a, z)
    split = [lambda r: r['bank'] and r['code'] == CMB, lambda r: r['bank'] and r['code'] != CMB]
    for label, a in (('全期', '2007-01'), ('2020 年起', '2020-01')):
        res['cmb'][label] = readout(rows, 3, a, '9999-12', split, ['招行', '其余银行'], rng=rng)
        res['cmb'][label + '（固定全期 b）'] = readout(rows, 3, a, '9999-12', split, ['招行', '其余银行'], b_fixed=b_full, rng=rng)
    groups = [lambda r: r['bank'] and r['code'] in BIG6, lambda r: r['bank'] and r['code'] in JOINT,
              lambda r: r['bank'] and r['code'] not in BIG6 and r['code'] not in JOINT]
    res['groups'] = readout(rows, 3, '2007-01', '9999-12', groups, ['国有大行', '股份行', '城农商行'], rng=rng)
    res['robust']['5 年·全期'] = readout(rows, 5, '2007-01', '9999-12', bank, ['bank'], rng=rng)
    res['robust']['5 年·2020 年起'] = readout(rows, 5, '2020-01', '9999-12', bank, ['bank'], rng=rng)
    res['robust']['全部样本·全期'] = readout(rows, 3, '2007-01', '9999-12', bank, ['bank'], panel_only=False, rng=rng)
    res['reproduce'] = dict(k=full['bank']['k'], registered=0.7045, ok=abs(full['bank']['k'] - 0.7045) < 5e-4)
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    write_md(res)


def write_md(res):
    pct = lambda v: f'{v * 100:+.2f}'
    ci = lambda v: f'[{v[0] * 100:+.2f}, {v[1] * 100:+.2f}]'
    kci = lambda v: f'[{v[0]:.2f}, {v[1]:.2f}]'
    out = ['# OI-244 读数：银行同尺系数的分时段、分组与招商银行单列', '',
           'c = 同 `P/V` 下银行较非金融的年化对数回报差（pp，负 = 银行更差）；b = 共同斜率；k = exp(−c ÷ b)，即银行 V 应乘的系数。'
           '区间为按股票整簇自助 1000 次的 90% 区间。面板在册、3 年期限，除注明外。',
           f"复现：全期 k = {res['reproduce']['k']:.4f}（在册 0.7045，{'一致' if res['reproduce']['ok'] else '不一致'}）。", '',
           '## 一、分时段（按起始月）', '',
           '| 时段 | 银行行／家 | b | c（pp） | c 区间 | k（自由斜率） | k 区间 | c（固定全期 b） | k（固定全期 b） | k 区间 | 银行内秩相关 |',
           '| --- | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: | --- | ---: |']
    for label, _a, _z in PERIODS:
        r, f, sp = res['periods'][label], res['periods_fixed_b'][label], res['spearman'][label]
        out.append(f"| {label} | {r['bank_rows']}／{r['bank_codes']} | {r['b']:.3f} | {pct(r['bank']['c'])} | {ci(r['bank']['c_ci'])} | "
                   f"{r['bank']['k']:.2f} | {kci(r['bank']['k_ci'])} | {pct(f['bank']['c'])} | {f['bank']['k']:.2f} | {kci(f['bank']['k_ci'])} | "
                   f"{sp['median']:+.2f} |")
    out += ['', '## 二、招商银行单列（招行与其余银行分设虚拟变量）', '',
            '| 口径 | c 招行 | 区间 | k 招行 | c 其余银行 | 区间 | k 其余 | 差值（招行 − 其余） | 差值区间 | 差值为正的抽样占比 |',
            '| --- | ---: | --- | ---: | ---: | --- | ---: | ---: | --- | ---: |']
    for label, r in res['cmb'].items():
        a, o, d = r['招行'], r['其余银行'], r['diff']
        out.append(f"| {label} | {pct(a['c'])} | {ci(a['c_ci'])} | {a['k']:.2f} | {pct(o['c'])} | {ci(o['c_ci'])} | {o['k']:.2f} | "
                   f"{pct(d['c'])} | {ci(d['c_ci'])} | {d['share_positive']:.0%} |")
    g = res['groups']
    out += ['', '## 三、银行分组（全期）', '', '| 组 | c（pp） | 区间 | k | k 区间 |', '| --- | ---: | --- | ---: | --- |']
    for name in ('国有大行', '股份行', '城农商行'):
        out.append(f"| {name} | {pct(g[name]['c'])} | {ci(g[name]['c_ci'])} | {g[name]['k']:.2f} | {kci(g[name]['k_ci'])} |")
    out += ['', '## 四、稳健性', '', '| 口径 | 银行行 | b | c（pp） | c 区间 | k | k 区间 |', '| --- | ---: | ---: | ---: | --- | ---: | --- |']
    for label, r in res['robust'].items():
        out.append(f"| {label} | {r['bank_rows']} | {r['b']:.3f} | {pct(r['bank']['c'])} | {ci(r['bank']['c_ci'])} | {r['bank']['k']:.2f} | {kci(r['bank']['k_ci'])} |")
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
