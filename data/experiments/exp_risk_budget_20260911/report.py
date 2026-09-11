"""Complete paired metrics, corrected experimental verdict, and event diagnostics."""
import ast
import collections
import contextlib
from datetime import date
import inspect
import json
import math
import statistics as st
import sys
from common import EXP, ROOT, REF, read, save, write, grid, numeric, sw
sys.path.insert(0,str(ROOT/'scripts/experimental'))
from oi148_slippage_report import clause4
from drawdown_path import episodes


def corrected_verdict():
    # Keep the authoritative implementation; isolate the documented OI-173 fix.
    src=inspect.getsource(sw.adoption_verdict)
    needle='if arm[s]["滚动5年为负的窗口占比"] > base[s]["滚动5年为负的窗口占比"]'
    assert src.count(needle)==1
    src=src.replace(needle,needle+' and base[s]["滚动5年为负的窗口占比"] == 0')
    namespace=dict(sw.__dict__)
    exec(compile(src,'<OI-173 experimental verdict>','exec'),namespace)
    return namespace['adoption_verdict']


def complete(groups):
    for group,arms in groups.items():
        for arm,starts in arms.items():
            assert set(starts)==set(sw.DEFAULT_STARTS),(group,arm)
            base=arms['BASE']
            for start,r in starts.items():
                assert r[sw.WIN5_KEY] and r[sw.WIN5_KEY].keys()==base[start][sw.WIN5_KEY].keys()
                assert len(r[sw.WIN5_KEY])==int(r['滚动5年窗口数'])
                for k in ['年化','最大回撤','滚动5年年化P25','滚动5年回撤中位','滚动5年为负的窗口占比']:
                    assert math.isfinite(r[k]),(group,arm,start,k)


def decision_printer():
    src=inspect.getsource(sw._print_decision)
    src=src.replace('负收益窗口占比变大的起点数','负收益窗口占比由0转正的起点数')
    ns=dict(sw.__dict__)
    exec(compile(src,'<OI-173 experimental display>','exec'),ns)
    return ns['_print_decision']


def prepare_display(arms,title):
    out=sw._prepare_group(arms,list(arms),[],title)
    adjusted=[]
    for sort,label,dz,n,med,old_neg in out['rows']:
        neg=sum(arms['BASE'][s]['滚动5年为负的窗口占比']==0 and
                arms[label][s]['滚动5年为负的窗口占比']>0 for s in sw.DEFAULT_STARTS)
        adjusted.append((sort,label,dz,n,med,neg))
    out['rows']=adjusted
    return out


def main():
    rows=read(EXP/'summary_rows.csv'); groups={}
    assert len(rows)==len({(r['group'],r['arm'],r['start'],int(r['bp'])) for r in rows}), 'duplicate path summaries'
    for r in rows:
        groups.setdefault((r['group'],int(r['bp'])),{}).setdefault(r['arm'],{})[r['start']]=numeric(r)
    complete(groups)
    verdict=corrected_verdict();decisions=[];metrics=[];tails=[];anchors=[];annual=[];events=[];risk=[];own=[];controls=[];costs=[]
    for (group,bp),arms in groups.items():
        if group in ('full','A') and bp==0:
            for arm in arms:
                if arm=='BASE' or arm.startswith('F'):continue
                for reference in ('F100','F120','F140'):
                    record=dict(group=group,arm=arm,reference=reference)
                    for key in ('年化','最大回撤','平均仓位','年均换手',sw.WIN5_KEY):
                        record[key]=st.median(sw.start_delta(arms[arm][s],arms[reference][s],key) for s in sw.DEFAULT_STARTS)
                    controls.append(record)
        for arm,starts in arms.items():
            if bp and group in ('full','A'):
                zero=groups[group,0][arm]
                record=dict(group=group,arm=arm,bp=bp,reference_bp=0)
                for key in ('年化','最大回撤','滚动5年回撤中位','最低担保比例',sw.WIN5_KEY):
                    record[key]=st.median(sw.start_delta(starts[s],zero[s],key) for s in sw.DEFAULT_STARTS)
                record['强平次数差']=sum(starts[s]['强平次数']-zero[s]['强平次数'] for s in sw.DEFAULT_STARTS)
                costs.append(record)
            for name,key,scale,_,__,good in sw.STANDARD_SET:
                ds=[sw.start_delta(starts[s],arms['BASE'][s],key) for s in sw.DEFAULT_STARTS]
                metrics.append(dict(group=group,bp=bp,arm=arm,metric=name,key=key,
                    level=st.median(r[key] for r in starts.values()),delta=st.median(ds),
                    better_count=sum(d*good>0 for d in ds),unit='ratio' if scale==1 else 'fraction'))
            for name,key in [('top1','单票权重中位'),('top1_p90','单票权重P90'),
                             ('top1_max','单票权重最大'),('top1_over60','单票超60%天数占比'),
                             ('top3','前三权重中位'),('positions','持仓数中位'),
                             ('rolling10_cagr','滚动10年年化中位')]:
                metrics.append(dict(group=group,bp=bp,arm=arm,metric=name,key=key,
                    level=st.median(r[key] for r in starts.values()),
                    delta=st.median(starts[s][key]-arms['BASE'][s][key] for s in sw.DEFAULT_STARTS),
                    better_count='',unit='descriptive'))
            worst=max(starts,key=lambda s:starts[s]['最大回撤'])
            least=min(starts,key=lambda s:starts[s]['滚动5年年化最差'])
            margin=min(starts,key=lambda s:starts[s]['最低担保比例'])
            buffer=min(starts,key=lambda s:starts[s]['最低股票同跌缓冲'])
            cash=min(starts,key=lambda s:starts[s]['最低现金'])
            tails.append(dict(group=group,bp=bp,arm=arm,max_mdd=starts[worst]['最大回撤'],
                mdd_start=worst,mdd_peak=starts[worst]['最大回撤起日'],mdd_trough=starts[worst]['最大回撤止日'],
                min_rolling5_cagr=starts[least]['滚动5年年化最差'],worst_window_start=least,
                worst_window_end=starts[least]['滚动5年年化最差窗口末日'],
                min_margin=min(r['最低担保比例'] for r in starts.values()),
                margin_start=margin,margin_date=starts[margin]['最低担保比例日'],
                min_buffer=min(r['最低股票同跌缓冲'] for r in starts.values()),
                buffer_start=buffer,buffer_date=starts[buffer]['最低股票同跌缓冲日'],
                min_cash=min(r['最低现金'] for r in starts.values()),
                cash_start=cash,cash_date=starts[cash]['最低现金日'],
                negative_cash_days=sum(r['负现金日数'] for r in starts.values()),
                forced_liquidations=sum(r['强平次数'] for r in starts.values()),
                liquidation_starts=sum(r['强平次数']>0 for r in starts.values()),
                negative_window_starts=sum(r['滚动5年为负的窗口占比']>0 for r in starts.values()),
                min_rf_coverage=min(r['rf覆盖率'] for r in starts.values()),
                data_end=max(r['末次净值日'] for r in starts.values())))
            for start in ('2009-11-01','2011-11-01'):
                anchors.append(dict(group=group,bp=bp,arm=arm,start=start,cagr=starts[start]['年化'],
                    cagr_delta=starts[start]['年化']-arms['BASE'][start]['年化'],mdd=starts[start]['最大回撤'],
                    mdd_delta=starts[start]['最大回撤']-arms['BASE'][start]['最大回撤']))
        if group=='full':
            other=groups['A',bp]
            for arm in arms:
                if arm=='BASE' or arm not in other:continue
                v,why,vals=verdict(arms,other,arm)
                old,oldwhy,_=sw.adoption_verdict(arms,other,arm)
                us=next((g for (g,b),a in groups.items() if b==0 and g.startswith('U') and arm in a),None)
                universal=clause4(groups[us,0],arm,'BASE')['第 4 款'] if us and bp==0 else (None,[])
                decisions.append(dict(arm=arm,bp=bp,verdict=v,reasons='；'.join(why),old_verdict=old,
                    old_reasons='；'.join(oldwhy),main_full=vals['主读数'][0],main_A=vals['主读数'][1],
                    cagr_full=vals['复利读数'][0],cagr_A=vals['复利读数'][1],
                    mdd_full=vals['ΔMDD'][0],mdd_A=vals['ΔMDD'][1],
                    u_group=us or '',u_qualified=universal[0],u_failures='；'.join(universal[1])))
    for row in rows:
        if row['bp']!='0':continue
        path=EXP/'raw'/row['nav_tag']/'nav.csv'
        # Reused U records point to the same A NAV; no extra execution assumed.
        nav=read(path); byday={r['date']:float(r['net_equity']) for r in nav}
        ends={}
        for d,v in byday.items():ends[d[:4]]=(d,v)
        prev=float(nav[0]['net_equity']);first_year=nav[0]['date'][:4]
        for y,(d,v) in sorted(ends.items()):
            annual.append(dict(group=row['group'],arm=row['arm'],start=row['start'],year=y,
                complete_year=y!=first_year and y<'2026',return_=v/prev-1));prev=v
        if row['group'] not in ('full','A'):continue
        own_eps=sorted(episodes(list(byday.items())),key=lambda x:-x[4])[:3]
        for rank,(peak,peq,trough,teq,dd,recovery) in enumerate(own_eps,1):
            own.append(dict(group=row['group'],arm=row['arm'],start=row['start'],rank=rank,
                peak=peak,trough=trough,drawdown=dd,recovery=recovery or '',
                peak_to_recovery_calendar_days=(date.fromisoformat(recovery)-date.fromisoformat(peak)).days if recovery else ''))
        if row['start'] in ('2009-11-01','2011-11-01'):
            base=next(r for r in rows if r['group']==row['group'] and r['arm']=='BASE' and
                      r['start']==row['start'] and r['bp']=='0')
            bn=read(EXP/'raw'/base['nav_tag']/'nav.csv')
            eps=sorted(episodes([(r['date'],float(r['net_equity'])) for r in bn]),key=lambda x:-x[4])[:7]
            for peak,peq,trough,teq,dd,recovery in eps:
                dates=[d for d in byday if peak<=d<=trough]
                initial=byday[peak]
                fixed_loss=1-byday[trough]/initial
                fixed_worst=1-min(byday[d] for d in dates)/initial
                recovered=next((d for d in byday if d>=trough and byday[d]>=initial),'')
                events.append(dict(group=row['group'],arm=row['arm'],start=row['start'],peak=peak,trough=trough,
                    base_drawdown=dd,peak_to_trough_loss=fixed_loss,delta_fixed_loss=fixed_loss-dd,
                    worst_loss_from_fixed_peak=fixed_worst,base_recovery=recovery or '',
                    recovered_after_base_trough=recovered))
        if row['arm']!='BASE':
            rs=read(EXP/'raw'/row['nav_tag']/'risk.csv')
            active=[r for r in rs if r['risk_dominant']=='True']
            spec=next(r for r in grid() if r['arm']==row['arm'])
            risk.append(dict(group=row['group'],arm=row['arm'],start=row['start'],days=len(rs),
                active_days=len(active),active_fraction=len(active)/len(rs),
                missing_days=sum(r['missing']=='True' for r in rs),
                mean_exposure=st.mean(float(r['exposure']) for r in rs),
                stress_overshoot_days=sum(float(r['stress20_top3'])>spec.get('budget',100)+1e-6 for r in rs),
                min_risk_cap=min([float(r['risk_cap']) for r in rs if r['risk_cap']] or [float('nan')]),
                first_active=active[0]['date'] if active else ''))
    for r in tails:
        for key in ('mdd_peak','mdd_trough','worst_window_end','margin_date','buffer_date','cash_date','data_end'):
            r[key]=sw._date_str(r[key])
    for name,data in [('decisions.csv',decisions),('standard_metrics.csv',metrics),('tails.csv',tails),
                      ('anchors.csv',anchors),('annual_paths.csv',annual),('same_interval_events.csv',events),('risk_activity.csv',risk),('own_episodes.csv',own),('fixed_control_comparisons.csv',controls),('cost_effects.csv',costs)]:
        write(name,data)
    save('followup.json',dict(passing_arms=[r['arm'] for r in decisions if r['bp']==0 and r['verdict'].startswith('可采纳')],
        u_qualified=[r['arm'] for r in decisions if r['bp']==0 and r['u_qualified']],
        oi173_verdict_flips=[r['arm'] for r in decisions if r['verdict']!=r['old_verdict']]))
    with (EXP/'formal_report.txt').open('w') as f,contextlib.redirect_stdout(f):
        for bp in sorted({b for g,b in groups if g=='full'}):
            full=prepare_display(groups['full',bp],f'全样本 {bp}bp')
            ex=prepare_display(groups['A',bp],f'A {bp}bp')
            for g in (full,ex):decision_printer()(g)
            print('【采纳判定：实验按成文OI-173口径】')
            for r in decisions:
                if r['bp']==bp: print(r['arm'],r['verdict'],r['reasons'])
            for g in (full,ex):sw._print_tail(g,sw.FIELDS)
            for g in (full,ex):sw._print_appendix(g)
    printed=EXP/'formal_report.txt'
    printed.write_text('\n'.join(line.rstrip() for line in printed.read_text().splitlines())+'\n')
    print('REPORT COMPLETE',len(decisions),'decisions')


if __name__=='__main__':main()
