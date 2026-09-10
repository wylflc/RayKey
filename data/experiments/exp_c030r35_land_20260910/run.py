"""Native BASE equivalence, current registration, and preserved E2/US compatibility."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import contextlib
import csv
from datetime import date,datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import statistics as st
import subprocess
import sys
from zoneinfo import ZoneInfo

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
REF=EXP.parent/'exp_c030r35_adoption_20260910'
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw
import screen_daily_volume_price_signals as scan


def read(path):
    with path.open() as f:return list(csv.DictReader(f))


def save(name,obj):
    (EXP/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def write(name,rows):
    with (EXP/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)


def fingerprint(paths):
    out={}
    for p in sorted(paths):
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1<<20),b''):h.update(block)
        out[str(p.relative_to(ROOT))]=dict(bytes=p.stat().st_size,sha256=h.hexdigest())
    return out


def prepare():
    previous=json.loads((REF/'manifest.json').read_text())
    paths={ROOT/p for p in previous['inputs']}
    changed={p for p,v in fingerprint(paths).items() if v!=previous['inputs'][p]}
    allowed={'scripts/'+p for p in ('equity_bond_constraint.py','backtest_valuation_strategy.py',
        'sweep_backtest_configs.py','screen_daily_volume_price_signals.py','strategy_return_tracker.py',
        'test_equity_bond_constraint.py','test_daily_execution_plan.py','test_strategy_parameter_sync.py',
        'test_strategy_return_tracker.py')}
    assert changed<=allowed,changed-allowed
    oldbase=previous['base']
    expected=oldbase.replace('--equity-bond-lower 1.0 --equity-bond-restore-above',
        '--equity-bond-lower 0.3 --equity-bond-restore-above --equity-bond-release-threshold 0.035')
    assert sw.BASE==expected and sw.DEFAULT_STARTS==previous['starts']
    oldsource=subprocess.check_output(['git','show','c24ea622:scripts/sweep_backtest_configs.py'],cwd=ROOT,text=True)
    old={'__name__':'frozen_baseline','__file__':str(ROOT/'scripts/sweep_backtest_configs.py')}
    exec(compile(oldsource,old['__file__'],'exec'),old)
    assert old['BASE']==oldbase and old['BASE_US']==sw.BASE_US
    for code,end in previous['price_ends'].items():
        with (ROOT/f'data/raw/ohlcv/{code}.csv').open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0,2);f.seek(max(0,f.tell()-4096));last=f.read().decode().splitlines()[-1].split(',')
        assert last[header.index('date')]==end
    paths|={EXP/p for p in ('run.py','engine.py','preregister.md')}
    paths|={ROOT/p for p in ('docs/000_Ashare_workflow.md','docs/000_personal-investment-system-v1.zh.md',
                            'scripts/slurm/c030r35_land_20260910.sbatch')}
    manifest=dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),job_id=os.environ.get('SLURM_JOB_ID'),
        base=sw.BASE,legacy_base=oldbase,base_us=sw.BASE_US,base_us_unchanged=True,starts=sw.DEFAULT_STARTS,
        changed_production_inputs=sorted(changed),other_prior_inputs_unchanged=True,inputs=fingerprint(paths),
        state_args=previous['state_args'],production_equivalence=previous['production_equivalence'],
        price_ends=previous['price_ends'],reference='exp_c030r35_adoption_20260910',reference_commit='c24ea622')
    save('manifest.json',manifest)
    print('PREPARE COMPLETE: data/equivalent states unchanged; only adopted BASE flags changed; BASE_US identical.',flush=True)
    return manifest


def one(job):
    group,start,excluded,manifest=job
    label='LEGACY' if group=='legacy' else 'BASE'
    tag=sw.summary_tag(label,start,','.join(excluded))
    out=EXP/'cache'/group;out.mkdir(parents=True,exist_ok=True)
    error=EXP/'errors'/f'{tag}.txt';error.parent.mkdir(exist_ok=True)
    base=manifest['legacy_base'] if group=='legacy' else manifest['base']
    cmd=[sys.executable,str(EXP/'engine.py'),*shlex.split(base),*manifest['state_args'],'--since',start,
         '--label-suffix','_'+tag,'--out-dir',str(out),'--equity-bond-log-dir',str(EXP/'daily'/group)]
    if excluded:cmd+=['--exclude-codes',','.join(excluded)]
    with error.open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=f,check=True)
    row=next(r for r in read(out/f'summary_{tag}.csv') if r['策略'].startswith('trend_'))
    return dict(group=group,arm=label,start=start,nav_tag=tag,**row)


def main():
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=12)
    p.add_argument('--verify-existing',action='store_true');args=p.parse_args()
    assert args.workers<=int(os.environ['SLURM_CPUS_PER_TASK'])
    verifier_changes={}
    if args.verify_existing:
        manifest=json.loads((EXP/'manifest.json').read_text())
        assert manifest['base']==sw.BASE and manifest['starts']==sw.DEFAULT_STARTS
        actual=fingerprint({ROOT/p for p in manifest['inputs']})
        verifier_changes={p:dict(before=manifest['inputs'][p],after=v) for p,v in actual.items() if v!=manifest['inputs'][p]}
        assert set(verifier_changes)<={str((EXP/p).relative_to(ROOT)) for p in ('run.py','preregister.md')}
    else:
        manifest=prepare()
    reference={(r['group'],r['arm'],r['start']):r for r in read(REF/'summary_rows.csv') if r['group'] in ('full','A')}
    a=sorted(reference['full','C030R35','2011-11-01']['前五赢家'].split('/'))
    # Candidate's new BASE winners equal A in the approved evaluation.
    assert a==sorted(json.loads((REF/'winner_dose_sets.json').read_text())['5'])
    jobs=[(g,s,a if g=='A' else [],manifest) for g in ('full','A') for s in sw.DEFAULT_STARTS]
    jobs += [('legacy',s,[],manifest) for s in ('2009-11-01','2011-11-01')]
    rows=[]
    if args.verify_existing:
        for g,s,excluded,_ in jobs:
            label='LEGACY' if g=='legacy' else 'BASE';tag=sw.summary_tag(label,s,','.join(excluded))
            r=next(r for r in read(EXP/'cache'/g/f'summary_{tag}.csv') if r['策略'].startswith('trend_'))
            rows.append(dict(group=g,arm=label,start=s,nav_tag=tag,**r))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for f in as_completed([pool.submit(one,j) for j in jobs]):
                rows.append(f.result());print(f'PATHS {len(rows)}/{len(jobs)}',flush=True)
    rows.sort(key=lambda r:(('full','A','legacy').index(r['group']),r['start']))
    fields_checked=nav_days=constraint_days=0;path_checks=[];rounding=[]
    for r in rows:
        group='full' if r['group']=='legacy' else r['group']
        arm='BASE' if r['group']=='legacy' else 'C030R35'
        ref=reference[group,arm,r['start']]
        assert set(r)-{'group','arm','start','nav_tag'}==set(ref)-{'group','arm','start','nav_tag'}
        for key in ref:
            if key in ('group','arm','start','nav_tag','策略'):continue
            if r[key]!=ref[key]:
                # This descriptive concentration fraction can differ by one final
                # floating-point bit. Decision fields and daily portfolios remain exact.
                assert key=='前五赢家占正贡献' and abs(float(r[key])-float(ref[key]))<=1e-15, (r['group'],r['start'],key,r[key],ref[key])
                rounding.append(dict(group=r['group'],start=r['start'],field=key,new=r[key],reference=ref[key],
                                     delta=float(r[key])-float(ref[key])))
            fields_checked+=1
        assert r['计量版本']==sw.METRIC_VERSION and int(r['负现金日数'])==0
        new=read(EXP/'nav'/f"{r['nav_tag']}.csv");old=read(REF/'nav'/f"{ref['nav_tag']}.csv")
        assert new==old,(r['group'],r['start'],'Daily portfolio mismatch')
        nav_days+=len(new)
        assert all(math.isfinite(float(x['net_equity'])) and float(x['net_equity'])>0 and float(x['cash'])>=-1e-6 for x in new)
        assert new[0]['date']==r['首个净值日'] and new[-1]['date']==r['末次净值日']=='2026-08-28'
        months={x['date'][:7] for x in new if x['date'][:7]<'2026-08'}
        number=lambda m:int(m[:4])*12+int(m[5:7])-1
        numbers={number(m) for m in months}
        expected={m for m in months if number(m)-60 in numbers}
        series=sw.parse_window_series(r[sw.WIN5_KEY])
        assert set(series)==expected and all(math.isfinite(x) for x in series.values())
        daily=read(EXP/'daily'/r['group']/f"_{r['nav_tag']}.csv")
        assert daily==read(REF/'daily'/group/f"_{ref['nav_tag']}.csv"),(r['group'],r['start'],'Constraint mismatch')
        constraint_days+=len(daily)
        for x in daily:assert x['observed_on']<=x['signal_day']<x['date']
        path_checks.append(dict(group=r['group'],start=r['start'],identical=True,nav_days=len(new),windows=len(series)))
    for group in ('full','A'):assert {r['start'] for r in rows if r['group']==group}==set(sw.DEFAULT_STARTS)
    sys.path.insert(0,str(EXP.parent/'exp_equity_bond_opt_20260910'))
    from policy import ResearchConstraint
    candidate=ResearchConstraint(scan.SEC93_EQUITY_BOND_DATA,mode='cap',metric='spread',threshold=.03,lower=1.,
        restore_above=True,spec=dict(kind='hysteresis',cap=.3,release=.035))
    signals=[]
    for day in reversed(candidate.days):
        prod=scan.equity_bond_signal(day);assert prod==candidate.resolve(day)
        signals.append(dict(observed_on=day,spread=prod[0].spread,cap=prod[1]))
    signals.reverse();write('signal_equivalence.csv',signals)
    current_day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    current,cap=scan.equity_bond_signal(current_day)
    save('current_signal.json',dict(as_of=current_day,observed_on=current.observed_on,spread=current.spread,cap=cap,
         trigger=scan.SEC93_EQUITY_BOND_THRESHOLD,release=scan.SEC93_EQUITY_BOND_RELEASE_THRESHOLD))
    write('summary_rows.csv',rows);write('path_checks.csv',path_checks)
    text=sw.metric_header()+'\n#MARKET|a\n#EX5|fixed|'+','.join(a)+'\n'
    for r in rows:
        if r['group']=='legacy':continue
        label=('EX5:' if r['group']=='A' else '')+'BASE'
        text+='|'.join([label,r['start']]+[f'{sw._field_value(r,k):.6f}' for k in sw.FIELDS])+'\n'
        text+=f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n"
    (EXP/'sweep_base.txt').write_text(text)
    with (EXP/'report_sweep_base.txt').open('w') as f,contextlib.redirect_stdout(f):sw.report(EXP/'sweep_base.txt','v4.178 生产BASE在册重登')
    report=EXP/'report_sweep_base.txt';report.write_text('\n'.join(x.rstrip() for x in report.read_text().splitlines())+'\n')
    register={}
    for g in ('full','A'):
        paths=[r for r in rows if r['group']==g]
        register[g]={k:st.median(sw._field_value(r,k) for r in paths) for k in sw.FIELDS}
        register[g]['长跑']={s:{k:float(next(r for r in paths if r['start']==s)[k]) for k in ('年化','最大回撤')}
                            for s in ('2009-11-01','2011-11-01')}
    save('in_register.json',register)
    actual=fingerprint({ROOT/p for p in manifest['inputs']})
    unchanged=all(v==manifest['inputs'][p] for p,v in actual.items() if p not in verifier_changes);assert unchanged
    assert all(actual[p]==v['after'] for p,v in verifier_changes.items())
    save('verification.json',dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        job_id=manifest['job_id'],native_base_paths=28,legacy_anchor_paths=2,all_summary_values_identical=not rounding,
        all_decision_and_standard_fields_exact=True,summary_equivalent_with_descriptive_rounding=True,descriptive_rounding=rounding,
        verifier_changes_after_first_run=verifier_changes,
        summary_fields_checked=fields_checked,daily_portfolio_rows_checked=nav_days,daily_constraint_rows_checked=constraint_days,
        exact_nav_cash_debt_positions_weights=True,complete_start_and_window_sets=True,negative_cash_days=0,
        live_signal_observations_identical=len(signals),base_us_unchanged=True,inputs_unchanged=unchanged,
        production_base_changed=True,epoch='E3',first_execution_date='2026-09-11'))
    print('NATIVE LAND VERIFICATION COMPLETE: 28 new BASE + 2 legacy daily paths and decision fields exact;',
          len(rounding),'descriptive last-bit differences.',flush=True)


if __name__=='__main__':main()
