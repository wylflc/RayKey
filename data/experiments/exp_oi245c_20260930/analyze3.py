"""OI-245 第三段读数（preregister.md「读数」「判据」），另出 OI-246 读数第 3 条（R1 公允性 λ）。

复用第二段的回归与公允性函数（`../exp_oi245b_20260930/analyze2.py`）：样本、种子、自助次数与区间都相同。
LG1.3 复现核对：按第二段的调用次序（先成因拆解、后 LG1.3）重算，λ 与区间须与 `readings2.json` 相同。

    python3 analyze3.py     # → readings3.json、readings3.md、cases3.csv
"""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP.parent / 'exp_oi245b_20260930'))
import analyze2 as a2  # noqa: E402
import observations3 as ob3  # noqa: E402

NAMES = [n for n, *_ in ob3.CANDIDATES]
NEW = ['LG1.3F', 'LG1.6F', 'LG2.0F']


def load():
    rows = []
    with (EXP / 'observations3.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            row = dict(code=r['code'], name=r['name'], gate=r['gate'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']),
                       y=a2.fnum(r['f3']), path=r['path'], lam=a2.fnum(r['lam']), w=a2.fnum(r['w']) or 0.0, v=a2.fnum(r['v']) or 0.0,
                       F1=a2.fnum(r['F1']), rec=a2.fnum(r['f1_recent']), old=a2.fnum(r['f1_old']))
            for n in NAMES + ['R1']:
                row[n] = a2.fnum(r[f'pv_{n}'])
            row['floor'] = r.get('floor_LG1.3F') == 'True'
            rows.append(row)
    return [r for r in rows if r['panel'] and r['y'] is not None and a2.PV_RANGE[0] <= r['pv'] <= a2.PV_RANGE[1]]


def removed_part(rows, rng):
    """读数 2：`y = a_月 + b·x + g1·d_F + g2·(d_LG − d_F)`，g2 ÷ b 为被下限撤回部分的 λ。"""
    x = lambda r: math.log(r['pv'])
    d_f = lambda r: math.log(r['LG1.3F']) - math.log(r['pv']) if r['LG1.3F'] and r['LG1.3'] else None
    d_rm = lambda r: math.log(r['LG1.3']) - math.log(r['LG1.3F']) if r['LG1.3F'] and r['LG1.3'] else None
    e = a2.regress(rows, [x, d_f, d_rm], ['d_F', 'removed'], rng)
    draws = e.pop('_draws')
    lam = lambda j: [float(np.nanpercentile(draws[:, j] / draws[:, 0], 5)), float(np.nanpercentile(draws[:, j] / draws[:, 0], 95))]
    removed_rows = [r for r in rows if r['floor'] and d_rm(r)]
    return dict(n=e['n'], b=e['b'], lam_F=e['d_F']['c'] / e['b'], lam_F_ci=lam(1), lam_removed=e['removed']['c'] / e['b'],
                lam_removed_ci=lam(2), verdict_removed=a2.lam_verdict(lam(2)), floor_rows=len(removed_rows),
                floor_codes=len({r['code'] for r in removed_rows}),
                mean_removed=float(np.mean([d_rm(r) for r in removed_rows])) if removed_rows else None)


def cases():
    """现行池：六只持仓、比亚迪、特宝与 LG1.3 下 V 降幅最大的 10 只，各列 LG1.3 与 LG1.3F（带层比例折算到 09-30 候选侧 P/V）。"""
    with (ROOT / 'data/processed/daily_buy_candidates.csv').open(newline='', encoding='utf-8') as f:
        cand = {r['security_code']: r for r in csv.DictReader(f)}
    latest, annual = {}, defaultdict(list)
    num = ob3.obs1.num
    with ob3.obs1.BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            c = r['security_code']
            if c not in cand or r['status'] != 'ok' or len(r['available_at']) != 10 or r['available_at'] > a2.SIGNAL:
                continue
            if r['report_date'].endswith('-12-31'):
                nopat, shares = num(r['nopat_ps']), num(r['shares_est'])
                annual[c].append(dict(fy=int(r['report_date'][:4]), av=r['available_at'],
                                      nopat=nopat * shares if nopat is not None and shares else None))
            if c not in latest or (r['available_at'], r['report_date']) > (latest[c]['available_at'], latest[c]['report_date']):
                latest[c] = r
    out = []
    for c, band in latest.items():
        if band['roic_path'] not in ob3.obs1.PATHS:
            continue
        nopat, shares, eps = num(band['nopat_ps']), num(band['shares_est']), num(band['eps_ttm'])
        base = nopat * shares if nopat is not None and shares else None
        prior = [a['nopat'] for a in ob3.obs1.history(annual[c], int(band['report_date'][:4]), band['available_at'], 5) if a['nopat'] is not None]
        m5 = statistics.median(prior) if len(prior) >= 3 else None
        v_band, nd, lam = num(band['intrinsic_value']), num(band['net_debt_ps']) or 0.0, num(band['growth_trust'])
        pv = a2.fnum(cand[c].get('model_pv'))
        row = dict(code=c, name=cand[c].get('security_name', ''), holding=c in a2.HOLDINGS or c in ('600036', '601318'), pv=pv, v=v_band,
                   ratio=base / m5 if base and m5 else None, eps_ttm=eps, nopat_ps=nopat)
        floor_total = eps * shares if eps is not None and eps > 0 and shares else None
        for name, t, floor in ob3.CANDIDATES:
            w, base_lg = ob3.ob2.guard(base, m5, lam, t, False)
            base2 = min(base, max(base_lg, floor_total)) if (w > 0 and floor and floor_total is not None) else base_lg
            v2 = (v_band + nd) * base2 / base - nd if w > 0 and base else v_band
            row[f'v_{name}'] = v2
            row[f'pv_{name}'] = pv * v_band / v2 if pv and v2 and v2 > 0 else None
        out.append(row)
    keep = {r['code'] for r in out if r['holding'] or r['code'] in ('002594', '688278')}
    drops = sorted((r for r in out if r['v_LG1.3'] and r['v']), key=lambda r: r['v_LG1.3'] / r['v'])[:10]
    keep |= {r['code'] for r in drops}
    sel = [r for r in out if r['code'] in keep]
    sel.sort(key=lambda r: (not r['holding'], (r['v_LG1.3'] or 0) / (r['v'] or 1)))
    with (EXP / 'cases3.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(sel[0])); w.writeheader(); w.writerows(sel)
    return sel


def main():
    rows = load()
    res = dict(sample=len(rows))
    # 复现：第二段调用次序（成因拆解先消耗随机数），LG1.3 主读数须与 readings2.json 相同
    rng = np.random.default_rng(a2.SEED)
    a2.diagnostics(rows, rng)
    rep = a2.fairness(rows, 'LG1.3', rng)
    reg2 = json.loads((EXP.parent / 'exp_oi245b_20260930/readings2.json').read_text())['candidates']['LG1.3']['main']
    res['reproduction'] = dict(lam=rep['lam'], lam_ci=rep['lam_ci'], registered_lam=reg2['lam'], registered_ci=reg2['lam_ci'],
                               identical=abs(rep['lam'] - reg2['lam']) < 1e-12 and all(abs(a - b) < 1e-12 for a, b in zip(rep['lam_ci'], reg2['lam_ci'])))
    print('reproduction', res['reproduction'], flush=True)
    rng = np.random.default_rng(a2.SEED)
    res['candidates'] = {}
    for name in NAMES:
        e = dict(main=a2.fairness(rows, name, rng))
        e['periods'] = {label: a2.fairness(rows, name, rng, a, z) for label, a, z in a2.PERIODS}
        e['residual_F1'] = a2.strip(a2.regress(rows, [lambda r, n=name: math.log(r[n]) if r[n] else None, lambda r: r['F1']], ['F1'], rng))
        e['zone'] = dict(current=a2.zone_share(rows, 'pv'), candidate=a2.zone_share(rows, name))
        res['candidates'][name] = e
        print(name, e['main'], flush=True)
    res['removed'] = removed_part(rows, rng)
    print('removed', res['removed'], flush=True)
    # OI-246 读数第 3 条：R1（谷底上调封顶 M5）的公允性 λ；主读数用全样本，另报只含 v > 0 行的样本
    r1 = dict(main=a2.fairness(rows, 'R1', rng))
    r1['v_rows_only'] = a2.fairness([r for r in rows if r['v'] > 0], 'R1', rng)
    r1['periods'] = {label: a2.fairness(rows, 'R1', rng, a, z) for label, a, z in a2.PERIODS}
    r1['zone'] = dict(current=a2.zone_share(rows, 'pv'), candidate=a2.zone_share(rows, 'R1'))
    res['R1'] = r1
    print('R1', r1['main'], flush=True)
    sel = cases()
    res['cases'] = sel
    (EXP / 'readings3.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str) + '\n')
    pp = lambda v: f'{v:+.2f}'
    ci = lambda v: f'[{v[0]:+.2f}, {v[1]:+.2f}]'
    md = ['# OI-245 第三段读数：水平守卫加当期 EPS 下限', '',
          f"样本：面板在册、3 年、`P/V` ∈ [0.2, 5] 的月末 {res['sample']} 行；按股票整簇自助 1000 次，90% 区间。", '',
          f"复现核对：LG1.3 λ {res['reproduction']['lam']:+.4f} {ci(res['reproduction']['lam_ci'])}，在册 {res['reproduction']['registered_lam']:+.4f} "
          f"{ci(res['reproduction']['registered_ci'])}，{'一致' if res['reproduction']['identical'] else '**不一致**'}。", '',
          '## 一、候选公允性 λ（主读数 LG1.3F）', '',
          '| 候选 | 变动行／家 | 平均 d | λ | λ 区间 | 判定 | 2007–2013 λ | 2014–2019 λ | 2020 年起 λ | 残余 F1 c | 区间 | 区内占比 现行→候选 |',
          '| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |']
    for name in NAMES:
        e = res['candidates'][name]
        m = e['main']
        per = [e['periods'][lab].get('lam') for lab, *_ in a2.PERIODS]
        rf = e['residual_F1']['F1'] if 'F1' in e['residual_F1'] else None
        md.append(f"| {name} | {m['moved']}／{m['moved_codes']} | {m['mean_d']:+.3f} | {m['lam']:+.2f} | {ci(m['lam_ci'])} | {m['verdict']} | "
                  + ' | '.join('—' if v is None else f'{v:+.2f}' for v in per)
                  + f" | {pp(rf['c'] * 100) if rf else '—'} | {ci([v * 100 for v in rf['c_ci']]) if rf else '—'} | "
                  f"{e['zone']['current']:.2%}→{e['zone']['candidate']:.2%} |")
    rm = res['removed']
    md += ['', f"**主读数判定（LG1.3F）：{res['candidates']['LG1.3F']['main']['verdict']}。**", '',
           '## 二、被下限撤回的部分', '',
           f"下限生效 {rm['floor_rows']} 行／{rm['floor_codes']} 家，平均撤回 {rm['mean_removed']:+.3f}（对数）。"
           f"合并式：保留部分 λ {rm['lam_F']:+.2f} {ci(rm['lam_F_ci'])}；撤回部分 λ {rm['lam_removed']:+.2f} {ci(rm['lam_removed_ci'])}（{rm['verdict_removed']}）。", '',
           '## 三、OI-246 读数第 3 条：R1（谷底上调封顶 M5）', '']
    m = r1['main']
    md.append(f"全样本：变动 {m['moved']} 行／{m['moved_codes']} 家，平均 d {m['mean_d']:+.3f}，λ {m['lam']:+.2f} {ci(m['lam_ci'])}，{m['verdict']}；"
              f"只含 v > 0 行：λ {r1['v_rows_only']['lam']:+.2f} {ci(r1['v_rows_only']['lam_ci'])}；分段 "
              + '、'.join(f"{lab} {r1['periods'][lab].get('lam', float('nan')):+.2f}" for lab, *_ in a2.PERIODS)
              + f"；区内占比 {r1['zone']['current']:.2%}→{r1['zone']['candidate']:.2%}。")
    md += ['', '## 四、现行池个案（09-30 候选侧 `P/V`）', '',
           '| 代码 | 名称 | 持仓 | 基数 ÷ M5 | 每股 NOPAT | EPS TTM | `P/V` | LG1.3 | LG1.3F | LG1.6F | LG2.0F |',
           '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    f2 = lambda v: '—' if v is None else f'{v:.2f}'
    for r in sel:
        md.append(f"| {r['code']} | {r['name']} | {'是' if r['holding'] else ''} | {f2(r['ratio'])} | {f2(r['nopat_ps'])} | {f2(r['eps_ttm'])} | "
                  f"{f2(r['pv'])} | {f2(r['pv_LG1.3'])} | {f2(r['pv_LG1.3F'])} | {f2(r['pv_LG1.6F'])} | {f2(r['pv_LG2.0F'])} |")
    (EXP / 'readings3.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print('\n'.join(md))


if __name__ == '__main__':
    main()
