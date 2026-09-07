#!/usr/bin/env python3
"""检查在册候选 K 剂量的配对完整性、符号一致性和原 A 表复现。"""
import json
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from sweep_backtest_configs import DEFAULT_STARTS, load_scan, STANDARD_SET

EXP = ROOT / 'data/experiments/exp_open_issues_20260907'
OLD = {
    **dict.fromkeys(['VT_E12','VS_MIN08'], 'exp_volume_trigger/sweep_stage1.txt'),
    **dict.fromkeys(['RC010','RC025','RC050'], 'exp_residual_clear/sweep_dose.txt'),
    **dict.fromkeys(['CNY40','CNY50','CNY60'], 'exp_residual_cny/sweep_dose.txt'),
    **dict.fromkeys(['FINAL50','FINAL60'], 'exp_residual_cny/sweep_final.txt'),
}


def main():
    groups, _order, failed, _note, metric, fields = load_scan(EXP / 'sweep_dose.txt')
    assert metric == 'm2' and not any(failed.values())
    rows = groups['EX5:']
    assert len(rows) == 44, len(rows)
    assert all(set(r) == set(DEFAULT_STARTS) for r in rows.values())
    results = {}
    report = ['# 在册候选赢家剔除剂量复核', '',
              '各格为逐起点配对差中位，单位百分点；列出全期年化，主读数另存dose_verification.json。同向性要求主读数和年化分别通过，±0.15pp视为噪声。', '',
              '| 候选 | K1 Δ年化 | K3 Δ年化 | K5 Δ年化 | K10 Δ年化 | 四档同向 | 反号指标 |',
              '| --- | ---: | ---: | ---: | ---: | --- | --- |']
    survivors = []
    for label, source in OLD.items():
        dose = {}
        for k in (1,3,5,10):
            tag = f'K{k}@OI160_164'
            base, arm = rows[tag+'BASE'], rows[tag+label]
            paired = {key: median(arm[s][key]-base[s][key] for s in DEFAULT_STARTS) for key in fields}
            standard = {name: {'level': median(arm[s][key] for s in DEFAULT_STARTS)*scale,
                               'base_level': median(base[s][key] for s in DEFAULT_STARTS)*scale,
                               'paired_delta': paired[key]*scale,
                               'positive_starts': sum((arm[s][key]-base[s][key])*good > 0 for s in DEFAULT_STARTS),
                               'unit': 'ratio' if scale == 1 else 'pp'}
                        for name,key,scale,_width,_prec,good in STANDARD_SET}
            dose[str(k)] = {'main_pp': paired['滚动5年年化中位']*100,
                            'cagr_pp': paired['年化']*100, 'standard': standard}
        crossed = []
        for key in ('main_pp', 'cagr_pp'):
            signs = {1 if r[key] > .15 else -1 if r[key] < -.15 else 0 for r in dose.values()}
            if {-1,1} <= signs:
                crossed.append(key)
        old = load_scan(ROOT/'data/experiments'/source)[0]['EX5:']
        old_a_exact = rows['K5@OI160_164'+label] == old[label]
        old_base_exact = rows['K5@OI160_164BASE'] == old['BASE']
        results[label] = {'dose': dose, 'crossed_metrics': crossed, 'same_direction': not crossed,
                          'old_a_exact': old_a_exact, 'old_base_exact': old_base_exact}
        if not crossed:
            survivors.append(label)
        report.append('| '+label+' | '+' | '.join(f"{dose[str(k)]['cagr_pp']:+.2f}" for k in (1,3,5,10))
                      +' | '+('通过此项，仍须后续验证' if not crossed else '失败')
                      +' | '+('/'.join({'main_pp':'主读数','cagr_pp':'年化'}[k] for k in crossed) or '无')+' |')
    payload = {'metric':metric, 'paths':616, 'starts':DEFAULT_STARTS, 'results':results,
               'next_margin_candidates':survivors}
    (EXP/'dose_verification.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    (EXP/'dose_review.zh.md').write_text('\n'.join(report)+'\n')
    print('\n'.join(report))
    print('Next margin candidates:', ','.join(survivors) or 'none')


if __name__ == '__main__':
    main()
