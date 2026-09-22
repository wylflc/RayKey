"""Pre-registered four-arm, fourteen-start full/A/individual-U paired runs."""
import csv
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from prepare import EXP,ROOT,digest
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw

ARMS={'BASE':0,'PV055':.55,'PV060':.6,'PV065':.65}
WORKERS=int(os.environ.get('PV_CAP_WORKERS','16'))


def save(name,value):
    (EXP/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def one(job):
    arm,start,group,excluded,native=job
    tag=sw.summary_tag(arm+group,start,','.join(excluded))
    cmd=[sys.executable,str(EXP/'engine.py'),*shlex.split(sw.BASE),
         '--since',start,'--label-suffix','_'+tag,'--out-dir',str(EXP/'cache'),
         '--equity-bond-log-dir',str(EXP/'daily')]
    for flag,name in (('--universe-file','pit_attention/panel_moat_bank_v6b.csv'),
        ('--daily-states','a_share_daily_states_adopted.csv'),('--hold-states','a_share_daily_states_hold.csv')):
        cmd += [flag,str(EXP/'inputs/data/processed'/name)]
    cmd += ['--equity-bond-data',str(EXP/'inputs/data/reference/equity_bond_csi300.csv')]
    if not native:cmd += ['--position-cap-pv-release',str(ARMS[arm])]
    if excluded:cmd += ['--exclude-codes',','.join(excluded)]
    env=dict(os.environ,PV_CAP_NATIVE='1' if native else '0')
    with (EXP/'errors'/f'{tag}.txt').open('w') as f:
        result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=f)
    assert result.returncode==0,(tag,result.returncode)
    with (EXP/'cache'/f'summary_{tag}.csv').open() as f:
        row=next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本']==sw.METRIC_VERSION
    assert row['负现金日数']=='0',(tag,row['负现金日数'])
    print('DONE',group,arm,start,flush=True)
    return dict(arm=arm,start=start,group=group,tag=tag,**row)


def batch(group,excluded,arms):
    jobs=[(a,s,group,excluded,False) for a in arms for s in sw.DEFAULT_STARTS]
    print('START',group,len(jobs),'paths',flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:rows=list(pool.map(one,jobs))
    return rows


def main():
    assert int(os.environ['SLURM_CPUS_PER_TASK'])>=WORKERS
    manifest=json.loads((EXP/'manifest.json').read_text())
    for p,meta in manifest['code_hashes'].items():assert digest(ROOT/p)==meta,p
    native=one(('BASE',sw.EX5_ANCHOR_START,'native',[],True))
    smoke=one(('BASE',sw.EX5_ANCHOR_START,'disabled',[],False))
    diffs={k:[native[k],smoke[k]] for k in (*sw.FIELDS,sw.WIN5_KEY) if native[k]!=smoke[k]}
    nav_same=(EXP/'nav'/f'{native["tag"]}.csv').read_bytes()==(EXP/'nav'/f'{smoke["tag"]}.csv').read_bytes()
    save('baseline_reproduction.json',dict(fields=len(sw.FIELDS)+1,differences=diffs,identical_nav=nav_same))
    assert not diffs and nav_same
    rows=batch('full',[],ARMS)
    winners={a:sorted(next(r for r in rows if r['arm']==a and r['start']==sw.EX5_ANCHOR_START)['前五赢家'].split('/')) for a in ARMS}
    A=winners['BASE'];unions={a:sorted(set(A)|set(winners[a])) for a in ARMS if a!='BASE'}
    save('winners.json',dict(A=A,U=unions,by_arm=winners))
    rows+=batch('A',A,ARMS)
    u_groups={};cache={tuple(A):'A'}
    for arm,U in unions.items():
        if U==A:u_groups[arm]='A';continue
        # Each candidate uses exactly its own union, not the union of all candidates.
        group='U'+arm
        rows+=batch(group,U,('BASE',arm));u_groups[arm]=group
    fields=list(rows[0])
    with (EXP/'summary_rows.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    for p,meta in manifest['inputs'].items():assert digest(EXP/'inputs'/p)==meta,p
    for p,meta in manifest['code_hashes'].items():assert digest(ROOT/p)==meta,p
    save('completed.json',dict(paths=len(rows)+2,job_id=os.getenv('SLURM_JOB_ID'),
        unchanged_frozen_inputs=True,u_groups=u_groups,workers=WORKERS))


if __name__=='__main__':main()
