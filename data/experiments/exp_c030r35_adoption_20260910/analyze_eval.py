"""Strictly paired adoption audit; original standards plus scoped OI-172/173 guards."""
from collections import defaultdict
import contextlib
from datetime import date
import json
import math
import statistics as st
import sys
from common import EXP, ROOT, PRIOR, sw, read, write, save, load_module
sys.path.insert(0,str(PRIOR))
old=load_module('frozen_ebopt_analysis',PRIOR/'analyze.py')
from ex_winner_symmetry_report import CLAUSE4


def validate_nav(row,daily,base_dates):
    dates=tuple(r['date'] for r in daily)
    assert dates==base_dates and len(set(dates))==len(dates) and list(dates)==sorted(dates)
    assert dates[0]==row['首个净值日'] and dates[-1]==row['末次净值日']
    assert all(math.isfinite(float(r['net_equity'])) and float(r['net_equity'])>0
               and float(r['cash'])>=-.000001 for r in daily)
    # Frozen August 2026 is partial. Independent calendar construction rejects
    # equal-but-incomplete window series on BOTH arms (OI-172).
    assert dates[-1]=='2026-08-28'
    months={d[:7] for d in dates if d[:7]<dates[-1][:7]}
    number=lambda m:int(m[:4])*12+int(m[5:7])-1
    numbers={number(m) for m in months}
    expected={m for m in months if number(m)-60 in numbers}
    series=sw.parse_window_series(row[sw.WIN5_KEY])
    assert set(series)==expected,'Incomplete calendar window series'
    assert len(series)==int(row['滚动5年窗口数'])
    assert all(math.isfinite(v) for v in series.values())
    years=(date.fromisoformat(dates[-1])-date.fromisoformat(dates[0])).days/365.25
    cagr=(float(daily[-1]['net_equity'])/3000000)**(1/years)-1
    assert abs(cagr-float(row['年化']))<.0000006,(cagr,row['年化'])


def metrics(paths,base):
    old.validate_pair(paths,base)
    a={s:old.numeric(r) for s,r in paths.items()}
    b={s:old.numeric(r) for s,r in base.items()}
    result=[]
    for key in (*sw.FIELDS,sw.WIN5_KEY):
        d=[sw.start_delta(a[s],b[s],key) for s in sw.DEFAULT_STARTS]
        levels=[a[s][key] for s in sw.DEFAULT_STARTS] if key!=sw.WIN5_KEY else []
        result.append(dict(metric=key,level_median=st.median(levels) if levels else '',
                           paired_delta_median=st.median(d),positive_starts=sum(v>0 for v in d)))
    return result


def clause4(deltas):
    inferior=[]
    for key,scale,good in CLAUSE4:
        d=deltas[key]*scale*good
        assert math.isfinite(d)
        tolerance,limit=(.005,.033) if scale==1 else (.15,1.)
        if d < -tolerance:inferior.append(dict(metric=key,oriented_delta=d,beyond_limit=d < -limit))
    return not inferior or (len(inferior)==1 and not inferior[0]['beyond_limit']),inferior


def same_direction(values,noise=0.):
    signs={1 if x>noise else -1 if x < -noise else 0 for x in values}
    return not ({-1,1} <= signs)


def platform(values,passed,center):
    i=values.index(center)
    if not passed[i]:return []
    lo=hi=i
    while lo>0 and passed[lo-1]:lo-=1
    while hi+1<len(values) and passed[hi+1]:hi+=1
    return values[lo:hi+1]


def path_details(groups):
    annual,blocks,anchors,actual,events,episodes=[],[],[],[],[],[]
    for group in ('full','A'):
        for start in sw.DEFAULT_STARTS:
            maps={a:read(EXP/'nav'/f"{groups[group][a][start]['nav_tag']}.csv") for a in ('BASE','C030R35')}
            byyear,monthly={},{}
            for arm,daily in maps.items():
                last=3000000.;byyear[arm]={};monthly[arm]={}
                for year in sorted({r['date'][:4] for r in daily}):
                    rows=[r for r in daily if r['date'].startswith(year)]
                    end=float(rows[-1]['net_equity'])
                    byyear[arm][year]=(end/last-1,rows[0]['date'],rows[-1]['date'])
                    last=end
                for r in daily:
                    if r['date'][:7] < daily[-1]['date'][:7]:monthly[arm][r['date'][:7]]=r
            for y,(b,first,last) in byyear['BASE'].items():
                c=byyear['C030R35'][y][0]
                annual.append(dict(group=group,start=start,year=y,first=first,last=last,
                    full_year=first[5:7]=='01' and last[5:7]=='12',BASE_pct=b*100,C030R35_pct=c*100,delta_pp=(c-b)*100))
            num=lambda m:int(m[:4])*12+int(m[5:7])-1
            textmonth=lambda n:f'{n//12:04}-{n%12+1:02}'
            end=max(monthly['BASE'])
            while textmonth(num(end)-60) in monthly['BASE']:
                begin=textmonth(num(end)-60)
                span=(date.fromisoformat(monthly['BASE'][end]['date'])-date.fromisoformat(monthly['BASE'][begin]['date'])).days/365.25
                vals={a:(float(monthly[a][end]['net_equity'])/float(monthly[a][begin]['net_equity']))**(1/span)-1 for a in maps}
                blocks.append(dict(group=group,start=start,begin=begin,end=end,BASE_pct=100*vals['BASE'],
                              C030R35_pct=100*vals['C030R35'],delta_pp=100*(vals['C030R35']-vals['BASE'])))
                end=begin
            for a in maps:
                bvals=[r[a+'_pct']/100 for r in blocks if r['group']==group and r['start']==start]
                assert abs(st.median(bvals)-float(groups[group][a][start]['互不重叠5年块中位']))<.0000006
            if start not in ('2009-11-01','2011-11-01'):continue
            base_row=groups[group]['BASE'][start]
            lo,hi=base_row['最大回撤起日'],base_row['最大回撤止日']
            episode=dict(group=group,start=start,BASE_peak_date=lo,BASE_trough_date=hi)
            for a,daily in maps.items():
                segment=[float(r['net_equity']) for r in daily if lo<=r['date']<=hi]
                peak=segment[0];mdd=0.
                for nav in segment:peak=max(peak,nav);mdd=max(mdd,1-nav/peak)
                episode[a+'_same_interval_mdd_pct']=100*mdd
                episode[a+'_interval_return_pct']=100*(segment[-1]/segment[0]-1)
            episode['same_interval_mdd_delta_pp']=episode['C030R35_same_interval_mdd_pct']-episode['BASE_same_interval_mdd_pct']
            episodes.append(episode)
            for arm in maps:
                row,base=groups[group][arm][start],groups[group]['BASE'][start]
                anchors.append(dict(group=group,arm=arm,start=start,cagr_pct=100*float(row['年化']),
                   cagr_delta_pp=100*(float(row['年化'])-float(base['年化'])),mdd_pct=100*float(row['最大回撤']),
                   mdd_delta_pp=100*(float(row['最大回撤'])-float(base['最大回撤']))))
                d=read(EXP/'daily'/group/f"_{row['nav_tag']}.csv")
                for r in d:
                    assert r['observed_on']<=r['signal_day']<r['date']
                    assert (date.fromisoformat(r['signal_day'])-date.fromisoformat(r['observed_on'])).days<=45
                active=[r for r in d if r['cap']!='']
                actual.append(dict(group=group,arm=arm,start=start,signal_days=len(d),restricted_days=len(active),
                     restricted_fraction=len(active)/len(d),average_exposure_pct=100*float(row['平均仓位']),
                     active_sales=sum(int(r['active_sells']) for r in d),unresolved_days=sum(r['unresolved']=='True' for r in d)))
                state=False
                for r in d:
                    now=r['cap']!=''
                    if now!=state:
                        events.append(dict(group=group,arm=arm,start=start,date=r['date'],signal_day=r['signal_day'],
                             observed_on=r['observed_on'],restricted=now,spread_pp=100*float(r['spread']),
                             exposure_pct=100*float(r['exposure'])))
                        state=now
    write('annual_paths.csv',annual);write('nonoverlap_blocks.csv',blocks)
    write('anchors.csv',anchors);write('policy_actual_anchors.csv',actual);write('policy_events.csv',events)
    write('anchor_same_interval_drawdown.csv',episodes)


def policy_equivalence(specs):
    from policy import ResearchConstraint
    histories=defaultdict(list);rows=[]
    for spec in specs:
        if spec['family'] not in ('control','center','neighborhood'):continue
        obj=ResearchConstraint(ROOT/'data/reference/equity_bond_csi300.csv',mode='cap',metric='spread',
              threshold=.03,lower=1.,restore_above=True,spec=spec)
        values=tuple((r['observed_on'],r['cap']) for r in obj.audit if '2009-10-01'<=r['observed_on']<='2026-08-27')
        histories[values].append(spec['arm'])
        rows.extend(dict(arm=spec['arm'],observed_on=d,cap=c) for d,c in values)
    write('monthly_caps.csv',rows)
    save('identical_policy_groups.json',[a for a in histories.values() if len(a)>1])


def main():
    verification=json.loads((EXP/'verification.json').read_text())
    assert verification['inputs_unchanged'] and verification['baseline_and_candidate_reproduced_paths']==56
    rows=read(EXP/'summary_rows.csv')
    groups=defaultdict(lambda:defaultdict(dict))
    for r in rows:
        assert r['start'] not in groups[r['group']][r['arm']]
        groups[r['group']][r['arm']][r['start']]=r
    specs=json.loads((EXP/'grid.json').read_text());registry={r['arm']:r for r in specs}
    assert set(groups['full'])==set(groups['A'])==set(registry) and len(registry)==52
    numerical={g:{a:{s:old.numeric(r) for s,r in paths.items()} for a,paths in arms.items()} for g,arms in groups.items()}
    dated={s:tuple(r['date'] for r in read(EXP/'nav'/f"{groups['full']['BASE'][s]['nav_tag']}.csv")) for s in sw.DEFAULT_STARTS}
    seen=set();paired=[];index={}
    for group,arms in groups.items():
        for arm,paths in arms.items():
            old.validate_pair(paths,arms['BASE'])
            for start,r in paths.items():
                if r['nav_tag'] not in seen:
                    validate_nav(r,read(EXP/'nav'/f"{r['nav_tag']}.csv"),dated[start]);seen.add(r['nav_tag'])
            refs=['BASE']
            if registry[arm]['family'] in ('margin','slip'):refs.append('B'+arm[1:])
            for ref in refs:
                if ref not in arms:continue
                records=metrics(paths,arms[ref])
                for r in records:
                    record=dict(group=group,arm=arm,ref=ref,**r)
                    paired.append(record);index[group,arm,ref,r['metric']]=r
    write('paired_metrics.csv',paired)
    delta=lambda g,a,k,ref='BASE':index[g,a,ref,k]['paired_delta_median']
    union_for={a:g for g,info in verification['union_groups'].items() for a in info['candidates']}
    decisions=[];decision_details={}
    short=(('cagr','年化'),('P',sw.WIN5_KEY),('mdd','最大回撤'),('p25','滚动5年年化P25'),
           ('worst5','滚动5年年化最差'),('roll5dd','滚动5年回撤中位'),('exposure','平均仓位'))
    for spec in specs:
        arm=spec['arm'];ref='B'+arm[1:] if spec['family']=='slip' else 'BASE'
        verdict,reasons,vals=old.checked_verdict(numerical['full'],numerical['A'],arm,ref)
        u=union_for.get(arm,'A')
        excellent,inferior=clause4({k:delta(u,arm,k,ref) for k,_,_ in CLAUSE4})
        row=dict(arm=arm,family=spec['family'],ref=ref,verdict=verdict,reasons='；'.join(reasons),
                 U=u,U_excellent=excellent,U_inferior=json.dumps(inferior,ensure_ascii=False))
        for alias,g in (('full','full'),('A','A'),('U',u)):
            for name,key in short:
                row[f'{alias}_{name}_delta_pp']=100*delta(g,arm,key,ref)
        decisions.append(row);decision_details[arm]=dict(readings=vals,U_inferior=inferior)
    write('decisions.csv',decisions);save('decision_details.json',decision_details)
    by={r['arm']:r for r in decisions}
    good=lambda a:by[a]['verdict'].startswith('可采纳')
    eligible=lambda a:good(a) and by[a]['U_excellent']
    caps=[20,25,30,35,40];releases=[300,325,350,375,400];margins=list(range(10,21))
    label=lambda c,r:'C030R35' if c==30 and r==350 else f'N{c:03}R{r}'
    marginlabel=lambda m:'C030R35' if m==15 else f'CM{m}'
    neighbor={kind:dict(cap=platform(caps,[fn(label(c,350)) for c in caps],30),
                               release=platform(releases,[fn(label(30,r)) for r in releases],350),
                               margin=platform(margins,[fn(marginlabel(m)) for m in margins],15))
              for kind,fn in (('section2',good),('section2_and_U',eligible))}
    save('platforms.json',neighbor)
    doses=[]
    for k in (1,3,5,10):
        g=f'K{k}'
        row=dict(K=k)
        for name,key in short:row[name+'_delta_pp']=100*delta(g,'C030R35',key)
        row['cagr_positive_starts']=index[g,'C030R35','BASE','年化']['positive_starts']
        row['mdd_shallower_starts']=sum(float(groups[g]['C030R35'][s]['最大回撤'])<float(groups[g]['BASE'][s]['最大回撤']) for s in sw.DEFAULT_STARTS)
        doses.append(row)
    write('winner_doses.csv',doses)
    costs=[]
    for bp in (0,10,20,30):
        a,b=('C030R35','BASE') if not bp else (f'CS{bp}',f'BS{bp}')
        for g in ('full','A'):
            row=dict(slippage_bp=bp,group=g,verdict=by[a]['verdict'])
            for name,key in short:
                row['candidate_'+name+'_delta_pp']=100*delta(g,a,key,b)
                row['BASE_cost_'+name+'_delta_pp']=100*delta(g,b,key)
            for side,arm in (('BASE',b),('candidate',a)):
                paths=numerical[g][arm]
                row[side+'_minimum_margin_ratio']=min(r['最低担保比例'] for r in paths.values())
                row[side+'_max_liquidations']=max(r['强平次数'] for r in paths.values())
                row[side+'_negative_cash_days']=sum(r['负现金日数'] for r in paths.values())
            costs.append(row)
    write('slippage.csv',costs)
    matched=[]
    for m in margins:
        a,b=('C030R35','BASE') if m==15 else (f'CM{m}',f'BM{m}')
        verdict,reasons,_=old.checked_verdict(numerical['full'],numerical['A'],a,b)
        row=dict(margin=m/100,verdict=verdict,reasons='；'.join(reasons))
        for g in ('full','A'):
            for name,key in short:row[g+'_'+name+'_delta_pp']=100*delta(g,a,key,b)
        matched.append(row)
    write('margin_matched.csv',matched)
    path_details(groups)
    policy_equivalence(specs)
    # Standard detailed tables retain fixed BASE comparisons. Slippage rows here
    # are explicitly NOT the cost verdict; slippage.csv contains same-cost pairs.
    combined=sw.metric_header()+'\n#MARKET|a\n#EX5|fixed|'+','.join(json.loads((EXP/'winner_dose_sets.json').read_text())['5'])+'\n'
    for g in ('full','A'):
        for spec in specs:
            for s in sw.DEFAULT_STARTS:
                r=groups[g][spec['arm']][s];label=('EX5:' if g=='A' else '')+spec['arm']
                combined+='|'.join([label,s]+[f'{sw._field_value(r,k):.6f}' for k in sw.FIELDS])+'\n'
                combined+=f"#WIN5|{label}|{s}|{r[sw.WIN5_KEY]}\n"
    (EXP/'sweep_full_A.txt').write_text(combined)
    sw.adoption_verdict=old.checked_verdict
    with (EXP/'report_full_A.txt').open('w') as f,contextlib.redirect_stdout(f):
        sw.report(EXP/'sweep_full_A.txt','30%/3.5pp采纳评估；固定BASE表；成本判定见slippage.csv')
    source=json.loads((EXP/'attribution.json').read_text())
    checklist=dict(section2=good('C030R35'),U_excellent=by['C030R35']['U_excellent'],
        neighbor_platform=all(len(neighbor['section2']['cap' if a=='cap' else 'release'])>=3 for a in ('cap','release')),
        margin_platform=len(neighbor['section2']['margin'])>=3,
        winner_cagr_same_direction=same_direction([r['cagr_delta_pp'] for r in doses]),
        winner_P_same_direction=same_direction([r['P_delta_pp'] for r in doses]),
        winner_cagr_same_direction_outside_noise=same_direction([r['cagr_delta_pp'] for r in doses],.15),
        winner_P_same_direction_outside_noise=same_direction([r['P_delta_pp'] for r in doses],.15),
        top3_net_share=source['top3_net_share'],attribution_usable=source['top3_net_share']<=1,
        signals_complete=verification['signals_complete'],slippage_passes={str(bp):good('C030R35' if not bp else f'CS{bp}') for bp in (0,10,20,30)})
    save('adoption_checklist.json',checklist)
    save('analysis_verification.json',dict(paths_checked=len(rows),unique_daily_paths=len(seen),arms=52,
        complete_start_and_window_sets=True,expected_calendar_windows_verified=True,daily_dates_equal=True,
        finite_decision_inputs=True,negative_cash_days=sum(int(r['负现金日数']) for r in rows),
        production_parameters_changed=False,production_verdict_issues='OI-172/173 scoped completeness and 0→positive guards'))
    for path in (EXP/'report_full_A.txt',):path.write_text('\n'.join(x.rstrip() for x in path.read_text().splitlines())+'\n')
    print(json.dumps(checklist,ensure_ascii=False,indent=2))
    print('ANALYSIS COMPLETE',len(rows),len(seen))


if __name__=='__main__':main()
