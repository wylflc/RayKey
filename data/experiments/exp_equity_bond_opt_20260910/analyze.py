"""Strict paired reports, current-versus-old BASE diagnosis and exportable plots."""
from collections import defaultdict
import contextlib
import csv
from datetime import date
import json
import math
from pathlib import Path
import statistics as st
import sys
from prepare import EXP, ROOT, save, sw
sys.path.insert(0, str(ROOT/'scripts/experimental'))
from ex_winner_symmetry_report import CLAUSE4


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with (EXP/name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def clean_exports():
    for path in [*EXP.glob('*.svg'),EXP/'report_full_A.txt']:
        if path.exists():
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines())+'\n')


def diagnostic():
    source = EXP.parent/'exp_ebds03_clause4_20260910/sig'
    nav = {}
    for arm, old in (('OFF','BASE'),('BASE','EBDS03')):
        current = EXP/'nav'/f'{arm}full20111101.csv'
        legacy = list((source/old).glob('*_equity.csv'))
        if current.exists():
            nav[arm] = read(current)
            if legacy:
                previous = read(legacy[0])
                assert len(previous) == len(nav[arm])
                for a,b in zip(nav[arm],previous):
                    assert a['date']==b['date'] and abs(float(a['net_equity'])-float(b['net_equity'])) < .011
        else:
            nav[arm] = read(legacy[0])
    assert [r['date'] for r in nav['BASE']] == [r['date'] for r in nav['OFF']]
    years = sorted({r['date'][:4] for r in nav['BASE']})
    annual, prior = [], dict(OFF=3000000., BASE=3000000.)
    for year in years:
        row = dict(year=year)
        for arm in ('OFF','BASE'):
            rs = [r for r in nav[arm] if r['date'].startswith(year)]
            end = float(rs[-1]['net_equity'])
            row[arm+'_return_pct'] = 100*(end/prior[arm]-1)
            row[arm+'_end_wealth'] = end
            row[arm+'_exposure_pct'] = 100*st.fmean((float(r['net_equity'])-float(r['cash'])+float(r['debt']))/
                                                        float(r['net_equity']) for r in rs)
            row[arm+'_debt_days'] = sum(float(r['debt'])>1 for r in rs)
            prior[arm] = end
        row['relative_wealth'] = prior['BASE']/prior['OFF']
        row['log_relative_return'] = math.log(1+row['BASE_return_pct']/100)-math.log(1+row['OFF_return_pct']/100)
        annual.append(row)
    write('diagnostic_annual.csv', annual)
    assert abs(sum(r['log_relative_return'] for r in annual)-math.log(annual[-1]['relative_wealth'])) < 1e-12
    current = EXP/'daily/full/_BASEfull20111101.csv'
    d = read(current if current.exists() else source/'EBDS03/_EBDS03.csv')
    events, active = [], False
    for i,r in enumerate(d):
        current = bool(r['cap'])
        if current != active:
            active = current
            events.append(dict(date=r['date'], observed_on=r['observed_on'], restricted=current,
                 spread_pp=100*float(r['spread']), exposure_pct=100*float(r['exposure']),
                 next_debt_day=next((x['date'] for x in d[i:] if float(x['debt'])>1),'')))
    write('diagnostic_events.csv', events)
    cycles = []
    for arm, old in (('OFF','BASE'),('BASE','EBDS03')):
        legacy = list((source/old).glob('*_trades.csv'))
        for r in (read(legacy[0]) if legacy else []):
            if r['security_code'] in ('002714','002466','600309','688516'):
                cycles.append(dict(arm=arm, **r))
    if cycles:
        write('diagnostic_cycles.csv', cycles)
    else:
        assert (EXP/'diagnostic_cycles.csv').exists(), 'Missing frozen cycle evidence'
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    dates = [date.fromisoformat(r['date']) for r in nav['BASE']]
    fig, axes = plt.subplots(3,1,figsize=(11,8),sharex=True,layout='constrained')
    for arm, color in (('OFF','#71717a'),('BASE','#007f87')):
        vals = [float(r['net_equity']) for r in nav[arm]]
        axes[0].plot(dates,[v/3e6 for v in vals],label=arm,color=color,lw=1.3)
        peak = 0; dd = []
        for v in vals:
            peak = max(peak,v); dd.append(100*(v/peak-1))
        axes[2].plot(dates,dd,color=color,lw=1)
    ratios = [float(a['net_equity'])/float(b['net_equity']) for a,b in zip(nav['BASE'],nav['OFF'])]
    axes[1].plot(dates,ratios,color='#007f87',lw=1.3)
    axes[1].axhline(1,color='#71717a',ls='--',lw=.8)
    axes[0].set_yscale('log'); axes[0].set_ylabel('Wealth / initial (log)'); axes[0].legend()
    axes[1].set_ylabel('BASE / OFF wealth'); axes[2].set_ylabel('Drawdown (%)')
    axes[0].set_title('2011-11 start: protection in 2015, different holdings afterwards')
    for ax in axes:
        ax.grid(alpha=.18)
        for a,b in (('2015-05-04','2015-08-03'),('2018-02-01','2018-03-01')):
            ax.axvspan(date.fromisoformat(a),date.fromisoformat(b),color='#e7a943',alpha=.18)
    fig.savefig(EXP/'diagnostic_2011.png',dpi=170)
    fig.savefig(EXP/'diagnostic_2011.svg')
    plt.close(fig)
    clean_exports()
    return annual


def numeric(row):
    return {**{k:sw._field_value(row,k) for k in sw.FIELDS}, sw.WIN5_KEY:sw.parse_window_series(row[sw.WIN5_KEY])}


def validate_pair(paths, base):
    assert set(paths) == set(base) == set(sw.DEFAULT_STARTS), 'Incomplete starts'
    for start in sw.DEFAULT_STARTS:
        a,b = paths[start],base[start]
        assert a['首个净值日']==b['首个净值日'] and a['末次净值日']==b['末次净值日']
        aw,bw = sw.parse_window_series(a[sw.WIN5_KEY]),sw.parse_window_series(b[sw.WIN5_KEY])
        assert aw and set(aw)==set(bw), (start,'Incomplete rolling windows')
        assert all(math.isfinite(v) for v in [*aw.values(),*bw.values()])
        assert all(math.isfinite(float(r[k])) for r in (a,b) for k in
                   ('年化','最大回撤','滚动5年回撤中位','滚动5年为负的窗口占比'))


def checked_verdict(arms_all, arms_ex, label, ref='BASE', **kwargs):
    # Scoped OI-173 mitigation: boolean incidence makes the existing comparison count exactly 0→positive.
    # All other verdict thresholds and drawdown channel logic are the repository's implementation.
    groups = []
    for arms in (arms_all, arms_ex):
        cloned = {}
        for arm, paths in arms.items():
            cloned[arm] = {s:dict(r, **{'滚动5年为负的窗口占比':float(r['滚动5年为负的窗口占比']>0)})
                           for s,r in paths.items()}
        groups.append(cloned)
    return original_verdict(*groups, label, ref=ref, **kwargs)


original_verdict = sw.adoption_verdict


def main():
    annual = diagnostic()
    verification = json.loads((EXP/'verification.json').read_text())
    assert verification['inputs_unchanged'] and verification['baseline_paths']==28
    rows = read(EXP/'summary_rows.csv')
    refined = (EXP/'refine_verification.json').exists()
    if refined:
        extra = json.loads((EXP/'refine_verification.json').read_text())
        assert extra['inputs_unchanged'] and extra['baseline_all_fields_identical']
        verification['union_groups'].update(extra['union_groups'])
        rows += read(EXP/'refine_rows.csv')
    groups = defaultdict(lambda:defaultdict(dict))
    for r in rows:
        assert r['start'] not in groups[r['group']][r['arm']]
        groups[r['group']][r['arm']][r['start']] = r
    numeric_groups, paired, anchors, nav_dates, actual = {}, [], [], {}, []
    for group, arms in groups.items():
        numeric_groups[group] = {}
        for arm, paths in arms.items():
            validate_pair(paths,arms['BASE'])
            numeric_groups[group][arm] = {s:numeric(r) for s,r in paths.items()}
            for start,r in paths.items():
                tag = r['nav_tag']
                if tag not in nav_dates:
                    daily = read(EXP/'nav'/f'{tag}.csv')
                    nav_dates[tag] = tuple(x['date'] for x in daily)
                    assert all(math.isfinite(float(x['net_equity'])) and float(x['net_equity'])>0 for x in daily)
                    # Independently derive the expected calendar windows: August 2026 is partial
                    # in this frozen snapshot, so only months before the final month are complete.
                    months = {x['date'][:7] for x in daily if x['date'][:7] < daily[-1]['date'][:7]}
                    number = lambda m:int(m[:4])*12+int(m[5:7])-1
                    numbered = {number(m) for m in months}
                    expected = {m for m in months if number(m)-60 in numbered}
                    assert set(sw.parse_window_series(r[sw.WIN5_KEY]))==expected, (group,arm,start,'Missing calendar window')
                    assert abs(float(daily[-1]['net_equity'])/3e6-
                               (1+float(r['年化']))**((date.fromisoformat(daily[-1]['date'])-
                                                     date.fromisoformat(daily[0]['date'])).days/365.25)) < .02
                base_tag = arms['BASE'][start]['nav_tag']
                assert base_tag in nav_dates
                assert nav_dates[tag] == nav_dates[base_tag], (group,arm,start,'Daily date mismatch')
            for key in (*sw.FIELDS,sw.WIN5_KEY):
                a,b = numeric_groups[group][arm],numeric_groups[group]['BASE']
                delta = [sw.start_delta(a[s],b[s],key) for s in sw.DEFAULT_STARTS]
                values = [a[s][key] for s in sw.DEFAULT_STARTS] if key!=sw.WIN5_KEY else []
                paired.append(dict(group=group,arm=arm,metric=key,
                    level_median=st.median(values) if values else '', paired_delta_median=st.median(delta),
                    positive_starts=sum(d>0 for d in delta), finite_delta_starts=sum(math.isfinite(d) for d in delta)))
            for start in ('2009-11-01','2011-11-01'):
                r,b = paths[start],arms['BASE'][start]
                anchors.append(dict(group=group,arm=arm,start=start,cagr_pct=100*float(r['年化']),
                    cagr_delta_pp=100*(float(r['年化'])-float(b['年化'])),mdd_pct=100*float(r['最大回撤']),
                    mdd_delta_pp=100*(float(r['最大回撤'])-float(b['最大回撤']))))
                if group == 'full':
                    path = EXP/'daily'/group/f"_{r['nav_tag']}.csv"
                    if not path.exists() and arm!='OFF':
                        matches = list((EXP/'daily').glob(f"*/_{r['nav_tag']}.csv"))
                        assert len(matches)==1
                        path = matches[0]
                    diagnostics = read(path) if path.exists() else []
                    assert diagnostics or arm == 'OFF'
                    for d in diagnostics:
                        assert d['observed_on'] <= d['signal_day'] < d['date']
                        assert (date.fromisoformat(d['signal_day'])-date.fromisoformat(d['observed_on'])).days <= 45
                    restricted = [d for d in diagnostics if d['cap'] != '']
                    actual.append(dict(arm=arm,start=start,signal_days=len(diagnostics),
                        restricted_days=len(restricted),restricted_fraction=len(restricted)/len(diagnostics) if diagnostics else 0,
                        average_exposure_pct=100*float(r['平均仓位']),
                        active_sales=sum(int(d['active_sells']) for d in diagnostics),
                        unresolved_days=sum(d['unresolved']=='True' for d in diagnostics)))
    write('paired_metrics.csv',paired); write('anchors.csv',anchors); write('policy_actual_anchors.csv',actual)
    idx = {(r['group'],r['arm'],r['metric']):r for r in paired}
    def delta(g,a,k):
        return idx[g,a,k]['paired_delta_median']
    union_for = {a:g for g,info in verification['union_groups'].items() for a in info['candidates']}
    specs = json.loads((EXP/'grid.json').read_text())
    if refined:
        specs += json.loads((EXP/'refine_grid.json').read_text())
    decisions = []
    sw.adoption_verdict = checked_verdict
    for spec in specs:
        arm = spec['arm']
        verdict, reasons, vals = checked_verdict(numeric_groups['full'],numeric_groups['A'],arm)
        u = union_for.get(arm,'A')
        inferior = []
        for k,scale,good in CLAUSE4:
            d = delta(u,arm,k)*scale*good
            tolerance,limit = (.005,.033) if scale==1 else (.15,1.)
            if d < -tolerance:
                inferior.append(dict(metric=k,delta=d,beyond_limit=d < -limit))
        excellent = not inferior or (len(inferior)==1 and not inferior[0]['beyond_limit'])
        row = dict(arm=arm,kind=spec['kind'],verdict=verdict,reasons='；'.join(reasons),
                   U=u,U_excellent=excellent,U_inferior=json.dumps(inferior,ensure_ascii=False))
        for g in ('full','A',u):
            alias = 'U' if g==u and g not in ('full','A') else g
            for short,k in (('cagr','年化'),('P',sw.WIN5_KEY),('mdd','最大回撤'),
                            ('p25','滚动5年年化P25'),('worst5','滚动5年年化最差'),
                            ('roll5dd','滚动5年回撤中位'),('exposure','平均仓位')):
                row[f'{alias}_{short}_delta_pp'] = 100*delta(g,arm,k)
                if k!=sw.WIN5_KEY:
                    row[f'{alias}_{short}_level_pct'] = 100*idx[g,arm,k]['level_median']
        if u=='A':
            row.update({k.replace('A_','U_',1):v for k,v in list(row.items()) if k.startswith('A_')})
        for start in ('2009-11-01','2011-11-01'):
            a = next(r for r in anchors if r['group']=='full' and r['arm']==arm and r['start']==start)
            row[f'anchor{start[:4]}_cagr_pct'] = a['cagr_pct']
            row[f'anchor{start[:4]}_mdd_pct'] = a['mdd_pct']
        decisions.append(row)
    decisions.sort(key=lambda r:r['full_cagr_delta_pp'],reverse=True)
    # Fields may be inserted in a different order for U=A; DictWriter maps by name.
    write('decisions.csv',decisions)
    combined = sw.metric_header()+'\n#MARKET|a\n#EX5|fixed|000338,000651,000933,002128,601088\n'
    for group in ('full','A'):
        for spec in specs:
            arm=spec['arm']
            for start in sw.DEFAULT_STARTS:
                row=groups[group][arm][start]
                label=('EX5:' if group=='A' else '')+arm
                combined += '|'.join([label,start]+[f'{sw._field_value(row,k):.6f}' for k in sw.FIELDS])+'\n'
                combined += f"#WIN5|{label}|{start}|{row[sw.WIN5_KEY]}\n"
    (EXP/'sweep_full_A.txt').write_text(combined)
    with (EXP/'report_full_A.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(EXP/'sweep_full_A.txt',f'融资约束{len(specs)}臂；OI-172完整性已校验，否决按0转正')
    save('analysis_verification.json',dict(paths_checked=len(rows),unique_daily_paths=len(nav_dates),
         complete_start_and_window_sets=True,expected_calendar_windows_verified=True,
         daily_dates_equal=True,finite_decision_inputs=True,
         arms=len(specs),refinement_included=refined,
         production_verdict_issues='OI-172/173 remain open; this experiment validates completeness and counts 0→positive',
         negative_cash_days=sum(int(r['负现金日数']) for r in rows),
         no_future_performance_claim=True))
    plot_grid(decisions)
    history = read(EXP/'policy_history.csv')
    if refined:
        history += read(EXP/'refine_policy_history.csv')
    histories = defaultdict(list)
    for r in history:
        if '2009-10-01' <= r['observed_on'] <= '2026-08-27':
            histories[r['arm']].append((r['observed_on'],r['cap']))
    equal = defaultdict(list)
    for arm,values in histories.items():
        equal[tuple(values)].append(arm)
    save('identical_policy_groups.json',[arms for arms in equal.values() if len(arms)>1])
    clean_exports()
    print('ANALYSIS COMPLETE; top full-CAGR candidates:')
    for r in decisions[:10]:
        print(r['arm'],r['verdict'],*[round(r[k],3) for k in
             ('full_cagr_delta_pp','A_cagr_delta_pp','full_P_delta_pp','full_mdd_delta_pp','anchor2011_cagr_pct')])


def plot_grid(decisions):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    by = {r['arm']:r for r in decisions}
    fig, axes = plt.subplots(1,3,figsize=(13,4.1),layout='constrained')
    for ax,key,title in zip(axes,('full_cagr_delta_pp','A_cagr_delta_pp','full_mdd_delta_pp'),
                           ('Full: paired CAGR change (pp)','Excluding A: CAGR change (pp)','Full: MDD change (pp; negative is shallower)')):
        data = np.array([[by['BASE' if c==100 and r==30 else f'C{c:03}R{r:02}'][key]
                          for r in (30,35,40,45,50)] for c in (0,30,50,80,100)])
        limit = max(abs(data.min()),abs(data.max()),.1)
        ax.imshow(data,cmap='RdBu' if 'mdd' not in key else 'RdBu_r',vmin=-limit,vmax=limit)
        for i in range(5):
            for j in range(5):
                ax.text(j,i,f'{data[i,j]:+.1f}',ha='center',va='center',
                        color='white' if abs(data[i,j])>limit*.55 else '#202020',fontsize=9)
        ax.set_xticks(range(5),('3','3.5','4','4.5','5'))
        ax.set_yticks(range(5),('0%','30%','50%','80%','100%'))
        ax.set_xlabel('Spread required to restore financing (pp)')
        ax.set_ylabel('Exposure cap while restricted'); ax.set_title(title,fontsize=10)
    fig.savefig(EXP/'hysteresis_grid.png',dpi=170)
    fig.savefig(EXP/'hysteresis_grid.svg')
    plt.close(fig)
    if 'C070R30' in by:
        fig, axes = plt.subplots(1,3,figsize=(12,3.6),layout='constrained')
        for ax,key,title in zip(axes,('full_cagr_delta_pp','A_cagr_delta_pp','A_roll5dd_delta_pp'),
                               ('Full CAGR change (pp)','Excluding A: CAGR change (pp)',
                                'Excluding A: rolling 5Y MDD change (pp)')):
            data = np.array([[by[f'C{c:03}R{r:02}'][key] for r in (30,35,40,45)] for c in (70,80,90)])
            limit = max(abs(data.min()),abs(data.max()),.1)
            ax.imshow(data,cmap='RdBu_r' if 'dd' in key else 'RdBu',vmin=-limit,vmax=limit)
            for i in range(3):
                for j in range(4):
                    ax.text(j,i,f'{data[i,j]:+.1f}',ha='center',va='center',fontsize=10,
                            color='white' if abs(data[i,j])>limit*.55 else '#202020')
            ax.set_xticks(range(4),('3','3.5','4','4.5'));ax.set_yticks(range(3),('70%','80%','90%'))
            ax.set_xlabel('Recovery spread (pp)');ax.set_ylabel('Restricted exposure');ax.set_title(title,fontsize=10)
        fig.savefig(EXP/'exposure_neighbors.png',dpi=170);fig.savefig(EXP/'exposure_neighbors.svg')
        plt.close(fig)


if __name__ == '__main__':
    if '--diagnostic-only' in sys.argv:
        diagnostic()
    else:
        main()
