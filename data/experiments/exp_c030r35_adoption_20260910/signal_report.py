"""Daily paired signal comparisons; full-support levels and common-day deltas separate."""
import json
import statistics as st
from common import EXP, write, save


def load(arm,name):return json.loads((EXP/'sig'/arm/name).read_text())


def describe(series):
    years={y:[v for d,v in series.items() if d[:4]==y] for y in sorted({d[:4] for d in series})}
    return dict(days=len(series),median_pp=100*st.median(series.values()) if series else None,
                positive_days=sum(v>0 for v in series.values()),years=len(years),
                positive_years=sum(st.median(v)>0 for v in years.values()))


def daily(result):return dict(zip(result.get('days',[]),result.get('diffs',[])))


def main():
    rows,years=[],[]
    for horizon in (250,750):
        loaded={a:load(a,f'selection_{horizon}d.json') for a in ('BASE','C030R35')}
        for metric in ('selection','swap','1_vs_2_5','1_vs_6_10'):
            source={a:daily(d[metric] if metric in ('selection','swap') else d['ranks_daily'][metric]) for a,d in loaded.items()}
            common=set(source['BASE'])&set(source['C030R35'])
            diff={d:source['C030R35'][d]-source['BASE'][d] for d in sorted(common)}
            r=dict(horizon=horizon,metric=metric)
            for name,s in (*source.items(),('paired_delta',diff)):
                r.update({name+'_'+k:v for k,v in describe(s).items()})
                for y in sorted({d[:4] for d in s}):
                    years.append(dict(horizon=horizon,metric=metric,arm=name,year=y,
                                      **describe({d:v for d,v in s.items() if d[:4]==y})))
            r.update(BASE_independent_pairs=loaded['BASE']['independent_pairs'],
                     C030R35_independent_pairs=loaded['C030R35']['independent_pairs'])
            rows.append(r)
        assert loaded['BASE']['ranks_pooled']==loaded['C030R35']['ranks_pooled']
        assert loaded['BASE']['ranks_daily']==loaded['C030R35']['ranks_daily']
    write('signal_comparison.csv',rows);write('signal_annual.csv',years)
    matched=[];bytol={}
    for tol in ('0.04','0.10','0.15'):
        bytol[tol]={a:load(a,f'swap_tol{tol}.json') for a in ('BASE','C030R35')}
        b,c=bytol[tol]['BASE'],bytol[tol]['C030R35']
        for key in ('panel_rho','panel_spread','synthetic'):
            assert b[key]==c[key],key
        for epoch,lo,hi in (('early','2011','2016'),('late','2017','2026')):
            for metric in ('actual','buy','sell','excess'):
                source={a:{d:r[metric] for d,r in values['daily'].items() if lo<=d[:4]<=hi}
                        for a,values in bytol[tol].items()}
                common=set(source['BASE'])&set(source['C030R35'])
                diff={d:source['C030R35'][d]-source['BASE'][d] for d in sorted(common)}
                row=dict(tolerance=tol,epoch=epoch,metric=metric)
                for name,s in (*source.items(),('paired_delta',diff)):
                    row.update({name+'_'+k:v for k,v in describe(s).items()})
                matched.append(row)
    write('swap_matched_comparison.csv',matched)
    mechanism=[]
    for a in ('BASE','C030R35'):
        first=bytol['0.04'][a]
        for y,synthetic in first['synthetic'].items():
            available=all(y in bytol[t][a]['per_year'] for t in bytol)
            if not available:continue
            actual=[bytol[t][a]['per_year'][y][1] for t in bytol]
            excess=[bytol[t][a]['per_year'][y][4] for t in bytol]
            sm=st.median(synthetic)
            stable=lambda vals:all(v>0 for v in vals) or all(v<0 for v in vals)
            row=dict(arm=a,year=y,synthetic_pp=sm*100,actual_sign_stable=stable(actual),
                excess_sign_stable=stable(excess),actual_opposite_synthetic_all_tolerances=all(v*sm<0 for v in actual),
                distinct_pairs=first['yearly_pairs'][y])
            for t,ac,ex in zip(bytol,actual,excess):row[t+'_actual_pp']=ac*100;row[t+'_excess_pp']=ex*100
            mechanism.append(row)
    write('swap_mechanism_years.csv',mechanism)
    save('signal_report_verification.json',dict(ranking_identical=True,panel_A_B_identical=True,
          same_day_delta_separate_from_levels=True,tolerances=['0.04','0.10','0.15'],
          returns_with_missing_horizon_excluded=True,independent_samples_not_daily_counts=True))
    print('SIGNAL REPORT COMPLETE')


if __name__=='__main__':main()
