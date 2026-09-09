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
    assert verification['inputs_unchanged'] and len(verification['baseline_checks']) == 28
    assert verification['completed_beijing'] >= json.loads((EXP/'manifest.json').read_text())['started_beijing']
    high_base = EXP.name == 'high_base'
    grid = json.loads((EXP / 'grid.json').read_text())
    groups = defaultdict(lambda: defaultdict(dict))
    with (EXP / 'summary_rows.csv').open() as f:
        for row in csv.DictReader(f): groups[row['group']][row['arm']][row['start']] = row
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
    union_for = {arm: group for group, info in verification['union_groups'].items() for arm in info['candidates']}
    decisions=[]; results=[]; paired_control=[]
    names={'BASE':'现行BASE','EBFIX160':'固定160%上限','EBFIX100':'固定100%上限',
           'EBQ20':'低于20%分位去融资','EBQ30':'低于30%分位去融资','EBQ40':'低于40%分位去融资',
           'EBS02':'利差低于2pp去融资','EBS03':'利差低于3pp去融资','EBS04':'利差低于4pp去融资',
           'EBCR30':'低于30%分位仅停新增融资','EBR10':'10～90%分位映射0～160%',
           'EBR20':'20～80%分位映射0～160%','EBR30':'30～70%分位映射0～160%'}
    names.update({'EBDQ20':'低20%分位去融资，其余BASE','EBDQ30':'低30%分位去融资，其余BASE','EBDQ40':'低40%分位去融资，其余BASE','EBDS02':'利差<2pp去融资，其余BASE','EBDS03':'利差<3pp去融资，其余BASE','EBDS04':'利差<4pp去融资，其余BASE','EBDC30':'低30%分位停新增，其余BASE'})
    control_arm = 'BASE' if high_base else 'EBFIX160'
    control_slug = 'base' if high_base else 'fixed160'
    for config in grid:
        arm=config['arm']; u=union_for.get(arm,'A')
        primary=[[m(g,arm,k)['paired_delta_median'] for g in ('full','A')] for k in ('年化','滚动5年年化中位')]
        numeric=numeric_verdict(primary)
        deeper=m('full',arm,'滚动5年回撤中位')['paired_delta_median']>sw.DRAWDOWN_GATE
        new_negative=sum(float(groups['full']['BASE'][s]['滚动5年为负的窗口占比'])==0 and
                         float(groups['full'][arm][s]['滚动5年为负的窗口占比'])>0 for s in sw.DEFAULT_STARTS)
        status=numeric if not deeper and new_negative<=len(sw.DEFAULT_STARTS)/2 else 'fail'
        inferior=[]
        for metric,scale,good in CLAUSE4:
            delta=m(u,arm,metric)['paired_delta_median']*scale*good
            if delta < -(.005 if scale==1 else .15):
                inferior.append({'metric':metric,'oriented_delta':delta,'beyond_tolerance':delta < -(.033 if scale==1 else 1)})
        excellent=not inferior or (len(inferior)==1 and not inferior[0]['beyond_tolerance'])
        decisions.append({'arm':arm,'kind':config['kind'],'numeric_verdict':numeric,'verdict':status,
                         'drawdown_gate':deeper,'new_negative_starts':new_negative,'U_group':u,'U_excellent':excellent,'U_inferior':inferior})
        result={'arm':arm,'name':names[arm],'kind':config['kind'],'verdict':status,'U_excellent':excellent,'U_group':u}
        for alias,group in (('full','full'),('A','A'),('U',u)):
            for slug,metric in (('cagr','年化'),('roll5','滚动5年年化中位'),('p25','滚动5年年化P25'),
                                ('roll5dd','滚动5年回撤中位'),('mdd','最大回撤'),('exposure','平均仓位'),
                                ('block5','互不重叠5年块中位'),('turnover','年均换手')):
                item=m(group,arm,metric)
                result[f'{alias}_{slug}_level']=item['level_median']
                result[f'{alias}_{slug}_delta_pp']=100*item['paired_delta_median']
        for group in ('full','A'):
            for metric in sw.FIELDS:
                changes=[sw._field_value(groups[group][arm][s],metric)-sw._field_value(groups[group][control_arm][s],metric) for s in sw.DEFAULT_STARTS]
                paired_control.append({'group':group,'arm':arm,'metric':metric,'paired_delta_median':st.median(changes)})
                if metric=='年化':result[f'{group}_cagr_vs_{control_slug}_pp']=100*st.median(changes)
        results.append(result)
    save('decisions.json',decisions)
    write_csv(f'paired_vs_{control_slug}.csv',paired_control)
    write_csv('results.csv',results)
    daily=[];yearly=[]
    for group_dir in sorted((EXP/'daily').iterdir()):
        if group_dir.name == 'full_A':
            valid_tags={'_'+sw.summary_tag(r['arm'],d,x) for r in grid if r['arm']!='BASE'
                        for d in sw.DEFAULT_STARTS for x in ('','fixed')}
        else:
            info=verification['union_groups'].get(group_dir.name)
            if info is None or info['reused_A']: continue
            valid_tags={'_'+sw.summary_tag(arm,d,'fixed') for arm in info['candidates'] for d in sw.DEFAULT_STARTS}
        for path in sorted(group_dir.glob('*.csv')):
            if path.stem not in valid_tags: continue
            with path.open() as f: records=list(csv.DictReader(f))
            assert records
            stats={'group':group_dir.name,'tag':path.stem,'days':len(records),
                'covered_days':sum(bool(r['observed_on']) and bool(r['percentile']) for r in records),
                'active_constraint_days':sum(bool(r['cap']) for r in records),
                'active_sale_days':sum(int(r['active_sells'])>0 for r in records),
                'active_sale_count':sum(int(r['active_sells']) for r in records),
                'below100_days':sum(bool(r['cap']) and float(r['cap'])<1 for r in records),
                'at100_days':sum(bool(r['cap']) and float(r['cap'])==1 for r in records),
                'unresolved_days':sum(r['unresolved']=='True' for r in records),
                'min_cash':min(float(r['cash']) for r in records)}
            new_deficits=[]; inherited_deficits=[]
            previous_cash=3e6
            for record in records:
                cash=float(record['cash'])
                if record['cap'] and cash < -1e-5:
                    (new_deficits if cash < min(0.,previous_cash)-1e-5 else inherited_deficits).append(record['date'])
                previous_cash=cash
            stats['new_active_cash_deficit_days']=len(new_deficits)
            stats['inherited_active_cash_deficit_days']=len(inherited_deficits)
            assert not new_deficits,(path,new_deficits)
            if not high_base: assert stats['min_cash']>=-1e-5,(path,stats['min_cash'])
            assert all(r['signal_day']<r['date'] and (not r['observed_on'] or r['observed_on']<=r['signal_day']) for r in records)
            daily.append(stats)
            prev=None
            for year in sorted({r['date'][:4] for r in records}):
                yearrows=[r for r in records if r['date'].startswith(year)]
                begin=prev if prev is not None else 3e6
                end=float(yearrows[-1]['equity'])
                yearly.append({'group':group_dir.name,'tag':path.stem,'year':year,'return':end/begin-1,
                     'partial_first_year':prev is None,'period_start':yearrows[0]['date'],'period_end':yearrows[-1]['date'],
                     'partial_last_year':year==records[-1]['date'][:4] and records[-1]['date'][5:7]!='12','exposure_mean':st.mean(float(r['exposure']) for r in yearrows),
                     'cap_mean':st.mean(float(r['cap']) for r in yearrows if r['cap']) if any(r['cap'] for r in yearrows) else ''})
                prev=end
    write_csv('signal_coverage.csv',daily);write_csv('yearly_overlay.csv',yearly)
    platforms=[]
    for kind in ('percentile','spread','ramp'):
        family=[r for r in results if r['kind']==kind]
        if len(family)==3 and all(r['verdict']=='pass' for r in family): platforms.append([r['arm'] for r in family])
    save('qa.json',{'input_hashes_unchanged':True,'baseline_paths_reproduced':28,'daily_paths':len(daily),
                    'new_active_cash_deficit_paths':0, 'legacy_negative_cash_paths':sum(r['min_cash'] < -1e-5 for r in daily),
                    'inherited_active_cash_deficit_days':sum(r['inherited_active_cash_deficit_days'] for r in daily),'timing_checks_passed':True,'platforms':platforms,
                    'unresolved_cap_days':sum(r['unresolved_days'] for r in daily)})
    text=['# 股债性价比：'+('仅低性价比去融资，其余恢复BASE' if high_base else '融资与总仓位约束回测'),'',
      '信号为沪深300整体滚动盈利收益率减中国10年国债收益率，按月更新，T+1执行。分位用此前最多60个月、至少12个月；性价比低时收紧仓位。',
      ('8臂中有7个新增信号候选。' if high_base else '13臂中有10个信号候选和2个固定上限控制。')+'全部Δ为14起点配对差中位，单位pp；回撤Δ负数表示改善。A去掉BASE前五赢家，U去掉双方赢家并集。',
      '', '| 配置 | Δ年化全 | Δ年化A | Δ年化U | Δ滚5全 | Δ滚5 A | Δ滚5回撤 | 平均仓位 | 判定 |',
      '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |']
    labels={'pass':'数值通过','ruling':'需裁定','fail':'未通过'}
    for r in sorted(results,key=lambda r:r['full_cagr_delta_pp'],reverse=True):
        cells=[f"{r[k]:+.2f}" for k in ('full_cagr_delta_pp','A_cagr_delta_pp','U_cagr_delta_pp','full_roll5_delta_pp','A_roll5_delta_pp','full_roll5dd_delta_pp')]
        text.append(f"| {r['name']} | "+' | '.join(cells)+f" | {r['full_exposure_level']:.1%} | {labels[r['verdict']]} |")
    text+=['','相邻三档全部数值通过的平台：'+str(platforms or '无')+'。','',
       '| 配置 | 对固定160% Δ年化全 | 对固定160% Δ年化A |','| --- | ---: | ---: |']
    for r in results:
        text.append(f"| {r['name']} | {r[f'full_cagr_vs_{control_slug}_pp']:+.2f} | {r[f'A_cagr_vs_{control_slug}_pp']:+.2f} |")
    text+=['',f"实际执行{verification['executed_paths']}条路径、汇总{verification['summary_rows']}行。BASE全/A共28条路径复现；生产子集等价与源哈希通过。",
        '信号覆盖与未达上限日见signal_coverage.csv；逐年结果见yearly_overlay.csv；完整标准集、尾部和长跑见paired_metrics.csv、tails.csv、anchors.csv及report_full_A.txt/report_U*.txt。',
        '冻结股票缓存净值末日2026-08-28；部分股票行情较旧，具体数量见manifest.json。数据来自供应商当前回溯历史，缺少历史发布版本校验，尚不能排除重述。',
        '这是历史初筛，没有新增样本外验证；未做采纳阶段的滑点/K/换仓边际重扫与信号层复核。生产规则保持。OI-167单股上限整手缺陷保持原样。']
    if high_base: text.append('OI-170：高状态保留BASE时继承原引擎负现金记账；低状态停新增融资臂存在从高状态延续的负现金。未把这些路径称为可执行资金验证通过，需修复基准后重算。')
    text.append('仓位守卫和exposure使用成交日可得收盘盯市；equity与收益指标继承BASE的记账口径，constraint_equity另记对应净资产。新增OI-169：新仓首日可能使用信号日价格盯市；本轮为共享现有记账口径的探索性诊断，采纳前必须修复并重算。')
    if high_base: text=[t.replace('对固定160%', '对BASE') for t in text]
    (EXP/'readout.md').write_text('\n'.join(text)+'\n')
    print('\n'.join(text[:22]))


if __name__=='__main__':main()
