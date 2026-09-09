"""Run the registered exposure neighbors with isolated files and unchanged first-stage evidence."""
import argparse
import csv
from datetime import datetime
import inspect
import json
import os
from zoneinfo import ZoneInfo
import run as runner
from prepare import EXP, ROOT, fingerprint, save, sw
from refine_engine import neighbors
from policy import ResearchConstraint


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workers',type=int,default=48)
    p.add_argument('--resume',action='store_true')
    args = p.parse_args()
    assert args.workers <= int(os.environ['SLURM_CPUS_PER_TASK'])
    first = json.loads((EXP/'verification.json').read_text())
    assert first['inputs_unchanged']
    manifest = json.loads((EXP/'manifest.json').read_text())
    assert fingerprint({ROOT/p for p in manifest['inputs']}) == manifest['inputs']
    protected = {EXP/p for p in ('refine.py','refine_engine.py','preregister_refine.md')}
    frozen = fingerprint(protected)
    save('refine_grid.json',neighbors())
    save('refine_manifest.json',dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'),inputs=frozen,first_manifest='manifest.json',new_candidates=8))
    history = []
    for spec in neighbors():
        c = ResearchConstraint(ROOT/'data/reference/equity_bond_csi300.csv',mode='cap',metric='spread',
                               threshold=.03,lower=1.,restore_above=True,spec=spec)
        history.extend(dict(arm=spec['arm'],**r) for r in c.audit)
    with (EXP/'refine_policy_history.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(history[0]),lineterminator='\n');w.writeheader();w.writerows(history)
    src = inspect.getsource(runner.one)
    assert src.count("EXP/'engine.py'")==1
    exec(compile(src.replace("EXP/'engine.py'","EXP/'refine_engine.py'"),__file__,'exec'),runner.__dict__)
    labels = ['BASE']+[r['arm'] for r in neighbors()]
    a = ['000338','000651','000933','002128','601088']
    full = runner.batch('Rfull',labels,[],args,manifest)
    stripped = runner.batch('RA',labels,a,args,manifest)
    old_rows = list(csv.DictReader((EXP/'summary_rows.csv').open()))
    old = {(r['group'],r['arm'],r['start']):r for r in old_rows}
    for row in full+stripped:
        row['group'] = 'full' if row['group']=='Rfull' else 'A'
        if row['arm']=='BASE':
            previous = old[row['group'],'BASE',row['start']]
            for k in (*sw.FIELDS,sw.WIN5_KEY,'前五赢家','首个净值日'):
                assert row[k]==previous[k],(row['group'],row['start'],k)
    rows = [r for r in full+stripped if r['arm']!='BASE']
    unions, winner_sets, union_groups = {}, {}, {}
    for arm in labels[1:]:
        anchor=next(r for r in full if r['arm']==arm and r['start']==sw.EX5_ANCHOR_START)
        b=set(anchor['前五赢家'].split('/'))-{''}
        u=tuple(sorted(set(a)|b))
        unions.setdefault(u,[]).append(arm)
        winner_sets[arm]=dict(A=a,B=sorted(b),U=list(u))
    executed = len(full)+len(stripped)
    for i,(u,candidates) in enumerate(unions.items(),1):
        group=f'RU{i}'
        reuse=set(u)==set(a)
        if reuse:
            source=old_rows+rows
            new=[dict(r,group=group) for r in source if r['group']=='A' and r['arm'] in ['BASE',*candidates]]
        else:
            new=runner.batch(group,['BASE',*candidates],list(u),args,manifest)
            executed+=len(new)
        rows+=new
        union_groups[group]=dict(codes=list(u),candidates=candidates,reused_A=reuse)
    with (EXP/'refine_rows.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
    assert fingerprint(protected)==frozen
    assert fingerprint({ROOT/p for p in manifest['inputs']})==manifest['inputs']
    save('refine_winner_sets.json',winner_sets)
    save('refine_verification.json',dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'),inputs_unchanged=True,baseline_paths=28,
         baseline_all_fields_identical=True,executed_paths=executed,summary_rows=len(rows),union_groups=union_groups))
    print(f'REFINEMENT COMPLETE {executed} paths',flush=True)


if __name__=='__main__':
    main()
