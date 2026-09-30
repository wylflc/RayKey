"""OI-232 候选读数（preregister.md 读数 1～5 与判据）。

同尺偏差：`log(1 + f_h) = a_月 + b·log(P/V) + c_保险·保险 + c_银行·银行`，非金融为参照，按股票整簇自助 1000 次，区间 90%。
非金融 `../exp_oi227_20260928/nonfin_v4216.csv`，银行（v4.224 不缩放）`../exp_oi230_20260929/bank_observations_DC_RAW.csv`。

    python3 analyze.py     # → readings.json、readings.md
"""
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
NONFIN = ROOT / 'data/experiments/exp_oi227_20260928/nonfin_v4216.csv'
BANKS = ROOT / 'data/experiments/exp_oi230_20260929/bank_observations_DC_RAW.csv'
CANDS = ('I0', 'I0c', 'I1', 'I1c', 'I2', 'I3')
LABELS = dict(I0='I0 现行 V_D0', I0c='I0c 去利率项', I1='I1 银行同法', I1c='I1c 银行同法·平滑 G', I2='I2 纯 DDM', I3='I3 非银权益路径')
RATE_FREE = {'I0c', 'I1c', 'I2', 'I3'}
USES_ROE = {'I1', 'I1c', 'I2', 'I3'}
PV_RANGE, BOOT, SEED = (0.2, 5.0), 1000, 20260930
SAMPLES = (('主读数：全部样本·全期·3 年', False, '2007-01', 3), ('面板·全期·3 年', True, '2007-01', 3),
           ('全部样本·2017 年起·3 年', False, '2017-01', 3), ('全部样本·全期·5 年', False, '2007-01', 5))
INDEPENDENT = dict(code='601318', base=66.5, low=50.0, high=85.0)


def fnum(v):
    return None if v in ('', 'None', None) else float(v)


def load_ref():
    rows = []
    for path, group in ((NONFIN, 'nonfin'), (BANKS, 'bank')):
        with path.open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f):
                pv = fnum(r['pv'])
                if pv is None:
                    continue
                rows.append(dict(code=r['code'].zfill(6), month=r['month'], panel=r['panel'] == 'True', pv=pv, f3=fnum(r['f3']),
                                 f5=fnum(r['f5']), group=group))
    return rows


def load_ins():
    with (EXP / 'candidates.csv').open(newline='', encoding='utf-8') as f:
        return [dict(r, panel=r['panel'] == 'True', f3=fnum(r['f3']), f5=fnum(r['f5']), rf=fnum(r['rf']),
                     **{f'pv_{k}': fnum(r[f'pv_{k}']) for k in CANDS}, **{f'v_{k}': fnum(r[f'v_{k}']) for k in CANDS})
                for r in csv.DictReader(f)]


def fit(y, x, D, t, w):
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    dm = lambda c: c - (np.bincount(t, weights=w * c) / safe)[t]
    X = np.column_stack([dm(x)] + [dm(D[:, j]) for j in range(D.shape[1])])
    Xw = X * w[:, None]
    beta = np.linalg.solve(X.T @ Xw, Xw.T @ dm(y))
    return float(beta[0]), beta[1:]


def same_ruler(ref, ins, cand, panel_only, since, h, rng):
    rows = [r for r in ref] + [dict(code=r['code'], month=r['month'], panel=r['panel'], pv=r[f'pv_{cand}'], f3=r['f3'], f5=r['f5'],
                                    group='ins') for r in ins if r[f'pv_{cand}'] is not None]
    sample = [r for r in rows if (r['panel'] or not panel_only) and r['month'] >= since and r[f'f{h}'] is not None
              and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]]
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    t = np.array([months[r['month']] for r in sample])
    s = np.array([codes[r['code']] for r in sample])
    y = np.log1p(np.array([r[f'f{h}'] for r in sample]))
    x = np.log(np.array([r['pv'] for r in sample]))
    D = np.column_stack([[float(r['group'] == 'ins') for r in sample], [float(r['group'] == 'bank') for r in sample]])
    b, c = fit(y, x, D, t, np.ones(len(y)))
    draws = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s]
        if (w * D[:, 0]).sum() == 0:
            continue                                 # 本次未抽到保险：c_保险 无定义
        try:
            bb, cc = fit(y, x, D, t, w)
        except np.linalg.LinAlgError:
            continue
        draws.append((bb, cc[0], cc[1]))
    d = np.array(draws)
    q = lambda v: [float(np.percentile(v, 5)), float(np.percentile(v, 95))]
    ins_rows = [r for r in sample if r['group'] == 'ins']
    return dict(n=len(sample), ins_rows=len(ins_rows), ins_codes=len({r['code'] for r in ins_rows}), draws=len(d), b=b,
                c_ins=float(c[0]), c_ins_ci=q(d[:, 1]), c_bank=float(c[1]), c_bank_ci=q(d[:, 2]),
                diff=float(c[0] - c[1]), diff_ci=q(d[:, 1] - d[:, 2]))


def dynamics(ins, cand):
    by = defaultdict(list)
    for r in ins:
        if r[f'v_{cand}'] and r['rf'] is not None:
            by[r['code']].append(r)
    dv, dr = [], []
    for rs in by.values():
        rs.sort(key=lambda r: r['month'])
        for a, b in zip(rs, rs[1:]):
            ya, ma = map(int, a['month'].split('-'))
            yb, mb = map(int, b['month'].split('-'))
            if (yb - ya) * 12 + mb - ma != 1:
                continue
            dv.append(math.log(b[f'v_{cand}'] / a[f'v_{cand}']))
            dr.append((b['rf'] - a['rf']) * 100)
    dv, dr = np.array(dv), np.array(dr)
    X = np.column_stack([np.ones(len(dr)), dr])
    slope = float(np.linalg.lstsq(X, dv, rcond=None)[0][1])
    big = np.abs(np.exp(dv) - 1) >= 0.10
    return dict(pairs=len(dv), rate_slope_per_pp=slope, jump_share=float(big.mean()),
                jump_median=float(np.median(np.abs(np.exp(dv[big]) - 1))) if big.any() else None)


def ranking(ins, cand):
    by = defaultdict(list)
    for r in ins:
        if r[f'pv_{cand}'] is not None and r['f3'] is not None:
            by[r['month']].append((r[f'pv_{cand}'], r['f3']))
    rho = [spearmanr([a for a, _ in xs], [b for _, b in xs])[0] for xs in by.values() if len(xs) >= 4]
    rho = [v for v in rho if v == v]
    return dict(months=len(rho), median=float(np.median(rho)) if rho else None, share_negative=float(np.mean([v < 0 for v in rho])) if rho else None)


def main():
    ref, ins = load_ref(), load_ins()
    current = json.loads((EXP / 'current.json').read_text())
    rng = np.random.default_rng(SEED)
    res = dict(reproduction=current['reproduction'], current=current, candidates={})
    for cand in CANDS:
        e = dict(same_ruler={}, dynamics=dynamics(ins, cand), ranking=ranking(ins, cand))
        for label, panel_only, since, h in SAMPLES:
            e['same_ruler'][label] = same_ruler(ref, ins, cand, panel_only, since, h, rng)
        main_r = e['same_ruler'][SAMPLES[0][0]]
        v_now = current['insurers'][INDEPENDENT['code']]['v'][cand]
        e['pingan_now'] = v_now
        e['acceptable'] = bool(main_r['c_ins_ci'][0] <= 0 <= main_r['c_ins_ci'][1] and v_now and INDEPENDENT['low'] <= v_now <= INDEPENDENT['high'])
        res['candidates'][cand] = e
        print(cand, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in main_r.items() if not isinstance(v, list)},
              [round(v, 4) for v in main_r['c_ins_ci']], e['dynamics'], e['ranking'], 'acceptable', e['acceptable'], flush=True)
    ok = [c for c in CANDS if res['candidates'][c]['acceptable']]
    ok.sort(key=lambda c: (c not in RATE_FREE, c not in USES_ROE, abs(res['candidates'][c]['same_ruler'][SAMPLES[0][0]]['c_ins'])))
    res['recommended'] = ok[0] if ok else 'I0'
    res['acceptable'] = ok
    (EXP / 'readings.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    write_md(res)


def write_md(res):
    pp = lambda v: f'{v * 100:+.2f}'
    ci = lambda v: f'[{v[0] * 100:+.2f}, {v[1] * 100:+.2f}]'
    cur = res['current']
    out = ['# OI-232 读数：保险估值六个候选（参考；任何改动由用户裁定）', '',
           f"I0 复现：{res['reproduction']['rows']} 个保险月末，与现行 `P/V` 不一致 {res['reproduction']['mismatch']} 个。"
           f"09-30：十年国债 {cur['rf'] * 100:.3f}%，前 10 年均值 {cur['rf_bar'] * 100:.3f}%；银行 G {cur['bank_g']:.4f}，前 36 个月中位 {cur['bank_g_bar']:.4f}；"
           f"招行核对 V_DDM {cur['cmb_check']['v_ddm']:.2f} × G = {cur['cmb_check']['v_h2']:.2f}。", '',
           '## 一、同尺偏差（c_保险：同 `P/V` 下保险较非金融的年化对数回报差，pp；负 = 保险 V 偏高）', '',
           '| 候选 | 样本 | 保险行／家 | b | c_保险 | 区间 | c_银行 | c_保险 − c_银行 | 区间 |',
           '| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | --- |']
    for cand in CANDS:
        for label, e in res['candidates'][cand]['same_ruler'].items():
            out.append(f"| {LABELS[cand]} | {label} | {e['ins_rows']}／{e['ins_codes']} | {e['b']:.3f} | {pp(e['c_ins'])} | {ci(e['c_ins_ci'])} | "
                       f"{pp(e['c_bank'])} | {pp(e['diff'])} | {ci(e['diff_ci'])} |")
    out += ['', '## 二、利率反应、阶跃与保险内排序', '',
            '| 候选 | 月度对数 | ln V 对国债（每 1pp） | 月变动 ≥ 10% 占比 | 其中位幅度 | 保险内秩相关中位（月数） | 平安 09-30 V | 可取 |',
            '| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |']
    for cand in CANDS:
        e = res['candidates'][cand]
        d, r = e['dynamics'], e['ranking']
        jump = '' if d['jump_median'] is None else f"{d['jump_median']:.1%}"
        rank = '' if r['median'] is None else f"{r['median']:+.2f}"
        now = '' if e['pingan_now'] is None else f"{e['pingan_now']:.2f}"
        out.append(f"| {LABELS[cand]} | {d['pairs']} | {d['rate_slope_per_pp']:+.3f} | {d['jump_share']:.1%} | {jump} | "
                   f"{rank}（{r['months']}） | {now} | {'是' if e['acceptable'] else '否'} |")
    out += ['', '## 三、09-30 现值（五家保险）', '', '| 代码 | 价格（日期） | ' + ' | '.join(LABELS[c] for c in CANDS) + ' |',
            '| --- | --- | ' + ' | '.join('---:' for _ in CANDS) + ' |']
    for code, e in cur['insurers'].items():
        cells = [f"{e['v'][c]:.2f}（{e['pv'][c]:.2f}）" if e['v'][c] and e['pv'][c] else '' for c in CANDS]
        out.append(f"| {code} | {e['price']}（{e['price_date']}） | " + ' | '.join(cells) + ' |')
    out += ['', '单元格为 V（`P/V`）。平安独立审视：基准 66.5，区间 50～85。', '',
            f"判据：可取 = 主读数 c_保险 区间含 0 且平安 09-30 V 在 50～85；可取者 {'、'.join(res['acceptable']) or '无'}；按预登记顺序推荐 **{res['recommended']}**。"]
    (EXP / 'readings.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print('\n'.join(out))


if __name__ == '__main__':
    main()
