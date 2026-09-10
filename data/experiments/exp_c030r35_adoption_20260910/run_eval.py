"""Complete the frozen full/A/U, margin, cost and winner-dose evaluation."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import csv
import json
import os
import shlex
import subprocess
import sys
from zoneinfo import ZoneInfo
from common import EXP, ROOT, PRIOR, sw, grid, read, write, save, fingerprint

REGISTRY={r['arm']:r for r in grid()}


def command(arm,start,tag,out,states,excluded=(),artifacts=False):
    base=shlex.split(sw.BASE)
    if artifacts:
        base.remove('--no-artifacts')
    cmd=[sys.executable,str(EXP/'engine.py'),*base,*states,*REGISTRY[arm]['extra'],
         '--eb-policy',arm,'--since',start,'--label-suffix','_'+tag,'--out-dir',str(out)]
    if excluded:
        cmd+=['--exclude-codes',','.join(excluded)]
    return cmd


def one(job):
    group,arm,start,excluded,states,resume=job
    tag=sw.summary_tag(arm+group,start,','.join(excluded))
    out=EXP/'cache'/group
    out.mkdir(parents=True,exist_ok=True)
    summary=out/f'summary_{tag}.csv'
    if not resume or not summary.exists():
        cmd=command(arm,start,tag,out,states,excluded)
        cmd+=['--equity-bond-log-dir',str(EXP/'daily'/group)]
        error=EXP/'errors'/f'{tag}.txt'
        error.parent.mkdir(exist_ok=True)
        with error.open('w') as f:
            proc=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=f)
        if proc.returncode:
            raise RuntimeError(f'{tag}: {error.read_text()[-3000:]}')
    row=next(r for r in read(summary) if r['策略'].startswith('trend_'))
    assert row['计量版本']==sw.METRIC_VERSION and row['负现金日数']=='0'
    assert (EXP/'nav'/f'{tag}.csv').exists()
    return dict(group=group,arm=arm,start=start,nav_tag=tag,**row)


def batch(group,arms,excluded,args,manifest):
    jobs=[(group,a,s,excluded,manifest['state_args'],args.resume) for a in arms for s in sw.DEFAULT_STARTS]
    print(f'{group} START {len(jobs)} paths, excluded={excluded}',flush=True)
    rows=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            rows.append(f.result())
            if len(rows)%50==0:
                print(f'{group} {len(rows)}/{len(jobs)}',flush=True)
    rows.sort(key=lambda r:(arms.index(r['arm']),r['start']))
    write(f'rows_{group}.csv',rows)
    return rows


def anchor(arm,manifest):
    out=EXP/'sig'/arm
    out.mkdir(parents=True,exist_ok=True)
    tag='SIG'+arm
    cmd=command(arm,'2011-11-01',tag,out,manifest['state_args'],artifacts=True)
    cmd+=['--candidate-log',str(out/'candidates.csv'),'--trade-log',str(out/'ledger.csv'),
          '--equity-bond-log-dir',str(out)]
    with (out/'run.log').open('w') as f:
        subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    row=next(r for r in read(out/f'summary_{tag}.csv') if r['策略'].startswith('trend_'))
    assert row['负现金日数']=='0'
    return row


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--workers',type=int,default=48)
    p.add_argument('--resume',action='store_true')
    args=p.parse_args()
    assert args.workers+5<=int(os.environ['SLURM_CPUS_PER_TASK'])
    manifest=json.loads((EXP/'manifest.json').read_text())
    assert manifest['base']==sw.BASE and manifest['starts']==sw.DEFAULT_STARTS
    assert fingerprint({ROOT/p for p in manifest['inputs']})==manifest['inputs']
    with ThreadPoolExecutor(max_workers=2) as pool:
        anchors=dict(zip(('BASE','C030R35'),pool.map(lambda a:anchor(a,manifest),('BASE','C030R35'))))
    save('anchor_summaries.json',anchors)
    sys.path.insert(0,str(ROOT/'scripts/experimental'))
    from delta_attribution import load_contrib
    contrib,is_contrib=load_contrib(next((EXP/'sig/BASE').glob('*_trades.csv')))
    assert is_contrib
    ranked=sorted(contrib,key=lambda c:(-contrib[c],c))
    a=set(anchors['BASE']['前五赢家'].split('/'))-{''}
    assert len(a)==5 and a==set(ranked[:5])
    center_u=sorted(a|set(anchors['C030R35']['前五赢家'].split('/')))
    save('winner_dose_sets.json',{str(k):ranked[:k] for k in (1,3,5,10)})
    save('ranked_winners.json',[dict(code=c,contrib=contrib[c]) for c in ranked])
    signal_log=(EXP/'signals_run.log').open('w')
    signals=subprocess.Popen([sys.executable,str(EXP/'signals.py'),'--all'],cwd=ROOT,
                             stdout=signal_log,stderr=subprocess.STDOUT)
    labels=list(REGISTRY)
    full=batch('full',labels,[],args,manifest)
    rows=full+batch('A',labels,sorted(a),args,manifest)
    previous={(r['group'],r['arm'],r['start']):r for r in read(PRIOR/'summary_rows.csv')
              if r['group'] in ('full','A') and r['arm'] in ('BASE','C030R35')}
    checks=0
    for r in rows:
        if r['arm'] not in ('BASE','C030R35'):
            continue
        old=previous[r['group'],r['arm'],r['start']]
        for k in (*sw.FIELDS,sw.WIN5_KEY,'前五赢家','首个净值日'):
            assert r[k]==old[k],(r['group'],r['arm'],r['start'],k,r[k],old[k])
        checks+=1
    assert checks==56
    print('BASE/C030R35 56 prior paths reproduced exactly.',flush=True)
    for k in (1,3,10):
        rows+=batch(f'K{k}',['BASE','C030R35'],ranked[:k],args,manifest)
    rows+=[dict(r,group='K5') for r in rows if r['group']=='A' and r['arm'] in ('BASE','C030R35')]
    unions,winner_sets={},{}
    for arm,spec in REGISTRY.items():
        if spec['family'] in ('control','margin_control','slip_control'):
            continue
        if spec['family']=='slip':
            u=tuple(center_u)
        else:
            row=next(r for r in full if r['arm']==arm and r['start']=='2011-11-01')
            u=tuple(sorted(a|set(row['前五赢家'].split('/'))))
        unions.setdefault(u,[]).append(arm)
        winner_sets[arm]=dict(A=sorted(a),U=list(u),fixed_at_zero_slippage=spec['family']=='slip')
    executed=len(full)*2+84
    union_groups={}
    for i,(u,candidates) in enumerate(unions.items(),1):
        group=f'U{i}'
        refs={'BASE'}
        for arm in candidates:
            if REGISTRY[arm]['family']=='slip':refs.add('B'+arm[1:])
            if REGISTRY[arm]['family']=='margin':refs.add('B'+arm[1:])
        group_labels=['BASE']+sorted(refs-{'BASE'})+candidates
        reuse=set(u)==a
        if reuse:
            new=[dict(r,group=group) for r in rows if r['group']=='A' and r['arm'] in group_labels]
        else:
            new=batch(group,group_labels,list(u),args,manifest)
            executed+=len(new)
        rows+=new
        union_groups[group]=dict(codes=list(u),candidates=candidates,controls=sorted(refs),reused_A=reuse)
    write('summary_rows.csv',rows)
    save('winner_sets.json',winner_sets)
    rc=signals.wait()
    signal_log.close()
    assert rc==0,f'Signal diagnostics failed: see {EXP}/signals_run.log'
    unchanged=fingerprint({ROOT/p for p in manifest['inputs']})==manifest['inputs']
    assert unchanged
    save('verification.json',dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'),inputs_unchanged=unchanged,
         baseline_and_candidate_reproduced_paths=checks,executed_paths=executed,anchor_artifact_paths=2,
         summary_rows=len(rows),union_groups=union_groups,signals_complete=True))
    print(f'EVALUATION COMPLETE {executed} formal paths + 2 artifact paths.',flush=True)


if __name__=='__main__':
    main()
