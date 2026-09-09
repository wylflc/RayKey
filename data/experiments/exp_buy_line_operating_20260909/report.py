"""Summarize every preregistered buy line with paired returns and risk gates."""
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
    assert verification['inputs_unchanged'] and len(verification['baseline_checks']) == 28
    grid = json.loads((EXP / 'grid.json').read_text())
    groups = defaultdict(lambda: defaultdict(dict))
    with (EXP / 'summary_rows.csv').open() as f:
        for row in csv.DictReader(f): groups[row['group']][row['arm']][row['start']] = row
    with (EXP / 'eligibility.csv').open() as f:
        eligible = {r['arm']: r for r in csv.DictReader(f)}
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
        r = {**config, 'eligible_share': float(e['eligible_share']),
             'eligible_delta_pp': 100 * (float(e['eligible_share']) - float(eligible['BASE']['eligible_share'])),
             'eligible_company_days': int(e['eligible_company_days']), 'observations': int(e['observations']),
             'current_value_eligible': int(e['current_value_eligible']),
             'current_value_trend_eligible': int(e['current_value_trend_eligible']),
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
    # Consecutive fine-grid passes; this identifies non-inferiority, not proven improvement.
    by_line = {r['buy_line']: r for r in results}
    runs = []; run = []
    for n in range(90, 121):
        row = by_line[n / 100]
        if row['verdict'] == 'pass' and row['engine_risk_gates_passed']:
            run.append(row)
        else:
            if len(run) >= 3: runs.append(run)
            run = []
    if len(run) >= 3: runs.append(run)
    platforms = [{'low': r[0]['buy_line'], 'high': r[-1]['buy_line'], 'count': len(r),
                  'middle': r[len(r)//2]['buy_line'], 'members': [x['arm'] for x in r],
                  'minimum_full_cagr_delta_pp': min(x['full_cagr_delta_pp'] for x in r),
                  'minimum_A_cagr_delta_pp': min(x['A_cagr_delta_pp'] for x in r)} for r in runs]
    save('platforms.json', platforms)
    by_start = []
    for row in results:
        arm = row['arm']
        for alias, group in (('full', 'full'), ('A', 'A'), ('U', row['U_group'])):
            for start in sw.DEFAULT_STARTS:
                p, b = groups[group][arm][start], groups[group]['BASE'][start]
                by_start.append({'arm': arm, 'buy_line': row['buy_line'], 'group': alias, 'exclusion_group': group,
                    'start': start, 'end': p['末次净值日'], 'cagr': p['年化'], 'base_cagr': b['年化'],
                    'delta_pp': 100 * (float(p['年化']) - float(b['年化']))})
    write_csv('cagr_by_start.csv', by_start)
    base = next(r for r in results if r['arm'] == 'BASE')
    ordered = sorted(results, key=lambda r: r['full_cagr_delta_pp'], reverse=True)
    text = ['# operating买入线扫描：完整结果', '',
        '47配置（BASE＋46候选，其中无上限仅作诊断）；其他参数固定当前BASE。A剔除BASE前五赢家，U剔除两臂赢家并集。',
        '全部Δ是14起点配对差的中位数，单位pp；回撤Δ为正表示变深。数值通过只是筛查结果，不代表生产采纳。',
        f"当前BASE：P/V≤1.0454，历史合格比例{base['eligible_share']:.3%}，全期CAGR中位{base['full_cagr_level']:.2%}，A为{base['A_cagr_level']:.2%}。", '',
        '| 买入线 | 合格比例 | Δ年化全 | Δ年化A | Δ年化U | Δ滚5全 | Δ滚5 A | Δ滚5回撤全 | 判定 | U资格 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |']
    labels = {'pass': '数值通过', 'ruling': '需裁定', 'fail': '未通过'}
    for r in ordered:
        label = 'BASE 1.0454' if r['arm'] == 'BASE' else '无上限（诊断）' if r['diagnostic'] else f"{r['buy_line']:g}"
        cells = [f"{r['eligible_share']:.3%}"] + [f"{r[k]:+.2f}" for k in
            ('full_cagr_delta_pp', 'A_cagr_delta_pp', 'U_cagr_delta_pp', 'full_roll5_delta_pp', 'A_roll5_delta_pp', 'full_roll5dd_delta_pp')]
        text.append(f"| {label} | " + ' | '.join(cells) + f" | {labels[r['verdict']]} | {'是' if r['U_excellent'] else '否'} |")
    text += ['', '0.90～1.20细网格的连续至少3档不劣区间（不将不劣自动称为收益改善）：']
    for p in platforms:
        text.append(f"- {p['low']:.2f}～{p['high']:.2f}，{p['count']}档，中位档{p['middle']:.2f}；区间最小Δ年化全/A={p['minimum_full_cagr_delta_pp']:+.2f}/{p['minimum_A_cagr_delta_pp']:+.2f}pp。")
    if not platforms: text.append('- 无。')
    diffs = [r['arm'] for r in decisions if r['risk_gates_passed'] != r['engine_risk_gates_passed']]
    text += ['', f'标准负窗否决（0转正）与引擎报告（占比增加）的风险判定差异臂：{diffs or "无"}。',
             '', '逐线比例见eligibility.csv；44字段水平/配对差/符号数见paired_metrics.csv；完整尾部、非重叠块、逐年与两个长跑锚点见report_full_A.txt和report_U*.txt。',
             f"执行{verification['executed_paths']}条路径、汇总{verification['summary_rows']}行；当前BASE全/A的28路径复现，输入哈希前后一致。",
             '冻结价格缓存的净值末日为2026-08-28；多数股票缓存止于8月7日或8月28日。没有新增样本外验证，OI-167原整手行为保留。']
    (EXP / 'readout.md').write_text('\n'.join(text) + '\n')
    print('\n'.join(text[:20]))
    print('Platforms:', platforms)
    print('U-qualified:', [r['buy_line'] for r in decisions if r['arm'] != 'BASE' and r['U_excellent']])


if __name__ == '__main__':
    assert numeric_verdict([[0, 0], [0, 0]]) == 'pass'
    assert numeric_verdict([[-.002, .012], [0, 0]]) == 'ruling'
    assert numeric_verdict([[-.002, .005], [0, 0]]) == 'fail'
    assert numeric_verdict([[-.02, .1], [0, 0]]) == 'fail'
    main()
