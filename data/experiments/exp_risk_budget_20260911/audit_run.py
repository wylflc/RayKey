"""Stream executed paths to audit timing, cash, caps and data coverage."""
import collections
import csv
import json
import math
from common import EXP, ROOT, read, save, write, digest, grid


def stream(path):
    with path.open(newline='') as f:
        yield from csv.DictReader(f)


def main():
    manifest=json.loads((EXP/'manifest.json').read_text())
    assert all(digest(ROOT/n)==h for n,h in manifest['inputs'].items())
    rows={r['nav_tag']:r for r in read(EXP/'summary_rows.csv')}
    specs={r['arm']:r for r in grid()}
    checks=[];exceptions=[];years=collections.defaultdict(lambda:collections.Counter())
    for tag,summary in rows.items():
        folder=EXP/'raw'/tag
        out=dict(nav_tag=tag,arm=summary['arm'],bp=int(summary['bp']),nav_rows=0,
                 negative_cash_days=0,min_cash=0.,risk_rows=0,causal_rows=0,
                 cap_overshoot_days=0,max_cap_overshoot=0.,unresolved_days=0,
                 active_sells=0,stress_overshoot_days=0,max_stress_overshoot=0.,
                 risk_dominant_days=0,missing_days=0)
        dates=[];prev=''
        for r in stream(folder/'nav.csv'):
            assert r['date']>prev;prev=r['date'];dates.append(prev)
            # Native initial-capital row has six fields; later rows add concentration.
            for k,v in r.items():
                if k in ('date','margin_ratio'):continue
                if v is None:
                    assert out['nav_rows']==0 and k in ('top1_weight','top3_weight')
                else:assert math.isfinite(float(v))
            out['nav_rows']+=1
            out['min_cash']=min(out['min_cash'],float(r['cash']))
            out['negative_cash_days']+=float(r['cash']) < -1e-6
        assert dates[-1]=='2026-08-28'
        assert out['negative_cash_days']==int(summary['负现金日数'])==0
        previous_execution='';cap_excess={}
        for r in stream(folder/'risk.csv'):
            out['risk_rows']+=1
            assert r['snapshot_day']<=r['signal_day']<r['date']
            assert r['date']>previous_execution
            if previous_execution:assert r['snapshot_day']==previous_execution
            previous_execution=r['date'];out['causal_rows']+=1
            if r['combined_cap']:
                excess=float(r['exposure'])-float(r['combined_cap'])
                out['cap_overshoot_days']+=excess>1e-6
                out['max_cap_overshoot']=max(out['max_cap_overshoot'],excess)
                if excess>1e-6:cap_excess[r['date']]=excess
            budget=specs[summary['arm']].get('budget')
            if budget is not None:
                excess=float(r['stress20_top3'])-budget
                out['stress_overshoot_days']+=excess>1e-6
                out['max_stress_overshoot']=max(out['max_stress_overshoot'],excess)
            active=r['risk_dominant']=='True';missing=r['missing']=='True'
            out['risk_dominant_days']+=active;out['missing_days']+=missing
            key=(summary['group'],summary['arm'],summary['bp'],r['date'][:4])
            years[key].update(days=1,active_days=active,missing_days=missing)
        if summary['arm']!='BASE':assert out['risk_rows']==out['nav_rows']-1
        records=0
        for r in stream(folder/f'_{tag}.csv'):
            records+=1
            assert r['signal_day']<r['date']
            out['unresolved_days']+=r['unresolved']=='True'
            out['active_sells']+=int(r['active_sells'])
            if summary['arm']!='BASE':
                assert (r['date'] in cap_excess)==(r['unresolved']=='True')
            if r['unresolved']=='True':
                exceptions.append(dict(nav_tag=tag,arm=summary['arm'],date=r['date'],
                    cap=r['cap'],exposure=r['exposure'],active_sells=r['active_sells'],
                    excess=cap_excess.get(r['date'],'')))
        assert records==out['nav_rows']-1
        checks.append(out)
    write('execution_checks.csv',checks)
    if exceptions:write('constraint_exceptions.csv',exceptions)
    write('coverage_by_year.csv',[dict(group=k[0],arm=k[1],bp=k[2],year=k[3],**v) for k,v in sorted(years.items())])
    save('execution_checks.json',dict(executed_paths=len(rows),
        nav_rows=sum(r['nav_rows'] for r in checks),risk_causal_rows=sum(r['causal_rows'] for r in checks),
        negative_cash_days=sum(r['negative_cash_days'] for r in checks),
        min_cash=min(r['min_cash'] for r in checks),
        cap_overshoot_days=sum(r['cap_overshoot_days'] for r in checks),
        max_cap_overshoot=max(r['max_cap_overshoot'] for r in checks),
        unresolved_days=sum(r['unresolved_days'] for r in checks),inputs_unchanged=True))
    print('EXECUTION AUDIT COMPLETE',len(rows))


if __name__=='__main__':main()
