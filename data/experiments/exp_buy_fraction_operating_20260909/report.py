"""Summarize daily cross-sectional buy fractions versus the unchanged fixed-line baseline."""
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics as st
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw
from ex_winner_symmetry_report import CLAUSE4


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_csv(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def numeric_verdict(deltas):
    ruling = False
    for full, a in deltas:
        low, high = min(full, a), max(full, a)
        if low < -sw.RULING_TOLERANCE: return 'fail'
        if low < -sw.NOISE_BAND:
            if high < sw.CLEAR_GAIN: return 'fail'
            ruling = True
    return 'ruling' if ruling else 'pass'


def main():
    verification = json.loads((EXP / 'verification.json').read_text())
    assert verification['inputs_unchanged'] and len(verification['baseline_checks']) == 56
    grid = json.loads((EXP / 'grid.json').read_text())
    groups = defaultdict(lambda: defaultdict(dict))
    with (EXP / 'summary_rows.csv').open() as f:
        for row in csv.DictReader(f): groups[row['group']][row['arm']][row['start']] = row
    with (EXP / 'selection_summary_full.csv').open() as f:
        eligible = {r['arm']: r for r in csv.DictReader(f) if r['year'] == 'ALL'}
    paired = []; index = {}
    directions = {r[1]: r[-1] for r in sw.STANDARD_SET}
    for group, arms in groups.items():
        base = arms['BASE']
        for arm, paths in arms.items():
            assert set(paths) == set(base) == set(sw.DEFAULT_STARTS)
            for metric in sw.FIELDS:
                values = [sw._field_value(paths[s], metric) for s in sw.DEFAULT_STARTS]
                changes = [sw._field_value(paths[s], metric) - sw._field_value(base[s], metric) for s in sw.DEFAULT_STARTS]
                r = {'group': group, 'arm': arm, 'metric': metric, 'level_median': st.median(values),
                     'paired_delta_median': st.median(changes), 'positive_starts': sum(d > 0 for d in changes),
                     'better_starts': sum(d * directions[metric] > 0 for d in changes) if metric in directions else ''}
                paired.append(r); index[(group, arm, metric)] = r
    write_csv('paired_metrics.csv', paired)
    paired_control = []
    for group in ('full', 'A'):
        control = groups[group]['FIX110FR09']
        for arm, paths in groups[group].items():
            if not arm.startswith('PCT'): continue
            for metric in sw.FIELDS:
                changes = [sw._field_value(paths[s], metric)-sw._field_value(control[s], metric) for s in sw.DEFAULT_STARTS]
                paired_control.append({'group': group, 'arm': arm, 'metric': metric,
                    'paired_delta_median': st.median(changes), 'positive_starts': sum(d > 0 for d in changes)})
    write_csv('paired_vs_fixed110.csv', paired_control)
    tails = []; anchors = []
    for group, arms in groups.items():
        for arm, paths in arms.items():
            values = list(paths.values())
            worst5 = min(values, key=lambda r: float(r['滚动5年年化最差']))
            maxdd = max(values, key=lambda r: float(r['最大回撤']))
            minratio = min(values, key=lambda r: float(r['最低担保比例']))
            minbuffer = min(values, key=lambda r: float(r['最低股票同跌缓冲']))
            tails.append({'group': group, 'arm': arm,
                'worst_roll5': worst5['滚动5年年化最差'], 'worst_roll5_start': worst5['start'],
                'worst_roll5_window_end': worst5['滚动5年年化最差窗口末日'],
                'worst_mdd': maxdd['最大回撤'], 'worst_mdd_start': maxdd['start'],
                'worst_mdd_from': maxdd['最大回撤起日'], 'worst_mdd_to': maxdd['最大回撤止日'],
                'lowest_margin_ratio': minratio['最低担保比例'], 'lowest_margin_ratio_start': minratio['start'],
                'lowest_margin_ratio_date': minratio['最低担保比例日'],
                'lowest_equity_buffer': minbuffer['最低股票同跌缓冲'], 'lowest_equity_buffer_start': minbuffer['start'],
                'lowest_equity_buffer_date': minbuffer['最低股票同跌缓冲日'],
                'forced_liquidations': sum(float(r['强平次数']) for r in values),
                'forced_liquidation_starts': sum(float(r['强平次数']) > 0 for r in values),
                'negative_window_starts': sum(float(r['滚动5年为负的窗口占比']) > 0 for r in values),
                'rf_coverage_min': min(float(r['rf覆盖率']) for r in values),
                'end': max(r['末次净值日'] for r in values)})
            for start in ('2009-11-01', '2011-11-01'):
                row, base = paths[start], arms['BASE'][start]
                anchors.append({'group': group, 'arm': arm, 'start': start, 'end': row['末次净值日'],
                    'cagr': row['年化'], 'cagr_delta_pp': 100 * (float(row['年化']) - float(base['年化'])),
                    'mdd': row['最大回撤'], 'mdd_delta_pp': 100 * (float(row['最大回撤']) - float(base['最大回撤']))})
    write_csv('tails.csv', tails); write_csv('anchors.csv', anchors)
    def m(group, arm, metric): return index[group, arm, metric]
    decisions = []; results = []
    for config in grid:
        arm = config['arm']
        u = 'A' if arm == 'BASE' else next(g for g in groups if g.startswith('U') and arm in groups[g])
        primary = [[m(g, arm, metric)['paired_delta_median'] for g in ('full', 'A')]
                   for metric in ('年化', '滚动5年年化中位')]
        numeric = numeric_verdict(primary)
        deeper = m('full', arm, '滚动5年回撤中位')['paired_delta_median'] > sw.DRAWDOWN_GATE
        negatives = [(float(groups['full']['BASE'][s]['滚动5年为负的窗口占比']),
                      float(groups['full'][arm][s]['滚动5年为负的窗口占比'])) for s in sw.DEFAULT_STARTS]
        new_negative = sum(a == 0 and b > 0 for a, b in negatives)
        increased_negative = sum(b > a for a, b in negatives)
        gate = not deeper and new_negative <= len(sw.DEFAULT_STARTS) / 2
        engine_gate = not deeper and increased_negative <= len(sw.DEFAULT_STARTS) / 2
        inferior = []
        for metric, scale, good in CLAUSE4:
            delta = m(u, arm, metric)['paired_delta_median'] * scale * good
            if delta < -(.005 if scale == 1 else .15):
                inferior.append({'metric': metric, 'oriented_delta': delta,
                                 'beyond_tolerance': delta < -(.033 if scale == 1 else 1)})
        excellent = not inferior or (len(inferior) == 1 and not inferior[0]['beyond_tolerance'])
        status = numeric if gate else 'fail'
        d = {**config, 'numeric_verdict': numeric, 'risk_gates_passed': gate,
             'engine_risk_gates_passed': engine_gate, 'drawdown_gate_triggered': deeper,
             'new_negative_starts': new_negative, 'increased_negative_starts': increased_negative,
             'verdict': status, 'U_group': u, 'U_excellent': excellent, 'U_inferior': inferior}
        decisions.append(d)
        e = eligible[arm]
        r = {**config, 'eligible_share': float(e['weighted_share']),
             'eligible_delta_pp': 100 * (float(e['weighted_share']) - float(eligible['BASE']['weighted_share'])),
             'eligible_company_days': int(e['selected_company_days']), 'observations': int(e['company_days']),
             'pv_cutoff_p10': float(e['cutoff_p10']), 'pv_cutoff_median': float(e['cutoff_median']),
             'pv_cutoff_p90': float(e['cutoff_p90']), 'days_cutoff_above_base': int(e['days_cutoff_above_base']),
             'signal_days': int(e['signal_days']),
             'potential_new_entry_company_days': int(e['potential_new_entry_company_days']),
             'potential_addon_company_days': int(e['potential_addon_company_days']),
             'U_group': u, 'verdict': status, 'U_excellent': excellent,
             'U_inferior_count': len(inferior), 'drawdown_gate_triggered': deeper,
             'new_negative_starts': new_negative, 'increased_negative_starts': increased_negative,
             'engine_risk_gates_passed': engine_gate}
        for alias, group in (('full', 'full'), ('A', 'A'), ('U', u)):
            for slug, metric in (('cagr', '年化'), ('roll5', '滚动5年年化中位'), ('roll5p25', '滚动5年年化P25'),
                                 ('roll5dd', '滚动5年回撤中位'), ('mdd', '最大回撤'), ('block5', '互不重叠5年块中位')):
                item = m(group, arm, metric)
                r[f'{alias}_{slug}_level'] = item['level_median']
                r[f'{alias}_{slug}_delta_pp'] = item['paired_delta_median'] * 100
                r[f'{alias}_{slug}_better_starts'] = item['better_starts']
        results.append(r)
    save('decisions.json', decisions)
    write_csv('results.csv', sorted(results, key=lambda r: r['full_cagr_delta_pp'], reverse=True))
    # Preregistered platform: at least three consecutive 1pp fractions passing all four metrics and gates.
    fractions = sorted([r for r in results if r['kind'] == 'fraction'], key=lambda r: r['value'])
    runs = []; run = []
    for row in fractions:
        if row['verdict'] == 'pass' and row['engine_risk_gates_passed']:
            run.append(row)
        else:
            if len(run) >= 3: runs.append(run)
            run = []
    if len(run) >= 3: runs.append(run)
    platforms = [{'low': r[0]['value'], 'high': r[-1]['value'], 'count': len(r),
                  'middle': r[len(r)//2]['value'], 'members': [x['arm'] for x in r],
                  'minimum_full_cagr_delta_pp': min(x['full_cagr_delta_pp'] for x in r),
                  'minimum_A_cagr_delta_pp': min(x['A_cagr_delta_pp'] for x in r)} for r in runs]
    save('platforms.json', platforms)
    by_start = []
    for row in results:
        arm = row['arm']
        for alias, group in (('full', 'full'), ('A', 'A'), ('U', row['U_group'])):
            for start in sw.DEFAULT_STARTS:
                p, b = groups[group][arm][start], groups[group]['BASE'][start]
                by_start.append({'arm': arm, 'kind': row['kind'], 'value': row['value'], 'group': alias, 'exclusion_group': group,
                    'start': start, 'end': p['末次净值日'], 'cagr': p['年化'], 'base_cagr': b['年化'],
                    'delta_pp': 100 * (float(p['年化']) - float(b['年化']))})
    write_csv('cagr_by_start.csv', by_start)
    base = next(r for r in results if r['arm'] == 'BASE')
    ordered = sorted(results, key=lambda r: r['full_cagr_delta_pp'], reverse=True)
    text = ['# operating横截面前x%买入扫描：完整结果', '',
        '9个比例候选（16%至24%每1pp），另BASE固定1.0454及固定1.10已知对照；其他参数不变。',
        '全部Δ是14起点配对差中位，单位pp；回撤Δ为正表示变深。A剔除BASE前五赢家，U剔除双方赢家并集，各自对同集BASE。',
        '比例是当日在册可估公司数的前x%，向下取整、同P/V按代码；先排名、后走势与执行约束。排名只用信号日信息。', '',
        '| 配置 | 实际入选比例 | 隐含P/V线中位 | Δ年化全 | Δ年化A | Δ年化U | Δ滚5全 | Δ滚5 A | Δ滚5回撤全 | 判定 | U资格 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    labels = {'pass': '数值通过', 'ruling': '需裁定', 'fail': '未通过'}
    for r in ordered:
        label = f"前{r['value']:.0%}" if r['kind'] == 'fraction' else f"固定{r['value']:g}" + ('（BASE）' if r['arm'] == 'BASE' else '（已知对照）')
        cells = [f"{r['eligible_share']:.3%}", f"{r['pv_cutoff_median']:.4f}"] + [f"{r[k]:+.2f}" for k in
            ('full_cagr_delta_pp', 'A_cagr_delta_pp', 'U_cagr_delta_pp', 'full_roll5_delta_pp', 'A_roll5_delta_pp', 'full_roll5dd_delta_pp')]
        text.append(f"| {label} | " + ' | '.join(cells) + f" | {labels[r['verdict']]} | {'是' if r['U_excellent'] else '否'} |")
    text += ['', '至少连续3档的数值通过区间：']
    for p in platforms:
        text.append(f"- 前{p['low']:.0%}～{p['high']:.0%}，{p['count']}档，中位档{p['middle']:.0%}；区间最小Δ年化全/A={p['minimum_full_cagr_delta_pp']:+.2f}/{p['minimum_A_cagr_delta_pp']:+.2f}pp。")
    if not platforms: text.append('- 无。')
    diffs = [r['arm'] for r in decisions if r['risk_gates_passed'] != r['engine_risk_gates_passed']]
    text += ['', f'标准负窗否决（0转正）与引擎报告（占比增加）的风险判定差异臂：{diffs or "无"}。',
             '', '比例统计覆盖2009-11首个实际信号日至缓存末端前一交易日；分母不同于上一轮包含早期年份的全部历史观察。潜在新建仓/加仓合格数只施走势、次日在册/有价条件，不等于有资金可实际执行的买单。',
             '逐日人数、隐含P/V线与逐年分布见daily_selection_*.csv及selection_summary_*.csv。44字段及长跑、融资尾部见paired_metrics.csv、anchors.csv、tails.csv和report_full_A.txt、report_U*.txt。',
             f"执行{verification['executed_paths']}条路径、汇总{verification['summary_rows']}行；两个固定线对照的56路径复现，源输入哈希一致。",
             '冻结价格缓存的净值末日为2026-08-28；155只票价格止于08-07，140只止于08-28，1只退市票止于2018-12-20。无新增样本外，OI-167原整手行为保持；初步筛查不自动采纳。']
    (EXP / 'readout.md').write_text('\n'.join(text) + '\n')
    print('\n'.join(text[:20]))
    print('Platforms:', platforms)
    print('U-qualified:', [r['value'] for r in decisions if r['kind'] == 'fraction' and r['U_excellent']])


if __name__ == '__main__':
    assert numeric_verdict([[0, 0], [0, 0]]) == 'pass'
    assert numeric_verdict([[-.002, .012], [0, 0]]) == 'ruling'
    assert numeric_verdict([[-.002, .005], [0, 0]]) == 'fail'
    assert numeric_verdict([[-.02, .1], [0, 0]]) == 'fail'
    main()
