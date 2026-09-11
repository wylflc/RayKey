import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo
from common import EXP, ROOT, REF, REVIEW, read, save, write, digest, grid, sw


def prepare():
    old=json.loads((REF/'manifest.json').read_text())
    review=json.loads((REVIEW/'verification.json').read_text())
    assert old['base']==sw.BASE and old['starts']==sw.DEFAULT_STARTS
    inputs={};frozen={}
    (EXP/'raw/frozen').mkdir(parents=True,exist_ok=True)
    for name,h in review['verified_input_hashes'].items():
        p=ROOT/name
        if name in review['historical_inputs_recovered']:
            q=EXP/'raw/frozen'/p.name
            if not q.exists():
                commit=review['historical_inputs_recovered'][name]['commit']
                q.write_bytes(subprocess.check_output(['git','show',f'{commit}:{name}'],cwd=ROOT))
            assert digest(q)==h
            frozen[name]=str(q.relative_to(EXP));inputs[str(q.relative_to(ROOT))]=h
        else:
            assert digest(p)==h,name
            inputs[name]=h
    ends={}
    for code,expected in old['price_ends'].items():
        p=ROOT/f'data/raw/ohlcv/{code}.csv'
        with p.open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0,2);f.seek(max(0,f.tell()-4096));last=f.read().decode().splitlines()[-1].split(',')
        ends[code]=last[header.index('date')];assert ends[code]==expected
    for p in list(EXP.glob('*.py'))+[EXP/'grid.json',EXP/'preregister.md',ROOT/'scripts/backtest_valuation_strategy.py',ROOT/'scripts/sweep_backtest_configs.py']:
        inputs[str(p.relative_to(ROOT))]=digest(p)
    manifest=dict(base=sw.BASE,starts=sw.DEFAULT_STARTS,state_args=old['state_args'],
        frozen=frozen,inputs=inputs,price_ends=ends,
        production_equivalence=old['production_equivalence'],
        prepared_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat())
    save('manifest.json',manifest);return manifest


def one(group,arm,start,excluded,manifest,bp=0,resume=True):
    tag=sw.summary_tag(f'RB{arm}{group}S{bp:03}',start,','.join(excluded))
    cache=EXP/'raw'/tag; cache.mkdir(parents=True,exist_ok=True)
    summary=cache/f'summary_{tag}.csv'
    if not (resume and summary.exists() and (cache/'nav.csv').exists()):
        command=[sys.executable,str(EXP/'engine.py'),*shlex.split(manifest['base']),
            *manifest['state_args'],'--risk-arm',arm,'--since',start,'--label-suffix','_'+tag,
            '--out-dir',str(cache),'--equity-bond-data',str(EXP/manifest['frozen']['data/reference/equity_bond_csi300.csv']),
            '--equity-bond-log-dir',str(cache),'--slippage-bp',str(bp)]
        if excluded: command+=['--exclude-codes',','.join(excluded)]
        with (cache/'stderr.txt').open('w') as f:
            result=subprocess.run(command,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=f)
        if result.returncode: raise RuntimeError(f'{tag}: '+(cache/'stderr.txt').read_text()[-2500:])
    row=next(r for r in read(summary) if r['策略'].startswith('trend_'))
    assert row['计量版本']=='m3' and int(row['负现金日数'])==0
    return dict(group=group,arm=arm,start=start,bp=bp,nav_tag=tag,excluded=','.join(excluded),**row)


def batch(group,arms,excluded,manifest,workers,bp=0):
    jobs=[(group,a,s,excluded,manifest,bp) for a in arms for s in sw.DEFAULT_STARTS]
    rows=[]
    print('BATCH',group,bp,len(jobs),'paths',flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,*job) for job in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows)%28==0: print('PROGRESS',group,bp,len(rows),'/',len(jobs),flush=True)
    rows.sort(key=lambda r:(arms.index(r['arm']),r['start']))
    write(f'rows_{group}_s{bp:03}.csv',rows)
    return rows


def same_nav(path,ref):
    rows,old=read(path),read(ref);assert len(rows)==len(old),(path,len(rows),len(old))
    for a,b in zip(rows,old):
        assert a.keys()==b.keys()
        for k in a:
            if k=='date': assert a[k]==b[k]
            elif a[k] is None and b[k] is None: continue
            else: assert float(a[k])==float(b[k]),(path,a['date'],k)
    return len(rows)


def validate_groups(rows):
    groups={}
    for r in rows: groups.setdefault((r['group'],r['arm'],r['bp']),{})[r['start']]=r
    for key,rs in groups.items():
        assert set(rs)==set(sw.DEFAULT_STARTS),key
        bases=groups[key[0],'BASE',key[2]]
        for start,r in rs.items():
            a=sw.parse_window_series(r[sw.WIN5_KEY]);b=sw.parse_window_series(bases[start][sw.WIN5_KEY])
            assert a and a.keys()==b.keys(),(key,start)
            assert len(a)==int(r['滚动5年窗口数'])
            assert all(__import__('math').isfinite(v) for v in a.values())
            assert r['末次净值日']=='2026-08-28'
    return len(groups)


def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',action='store_true');p.add_argument('--workers',type=int,default=12)
    args=p.parse_args();assert args.workers<=int(os.environ['SLURM_CPUS_PER_TASK'])
    manifest=prepare() if not (EXP/'manifest.json').exists() else json.loads((EXP/'manifest.json').read_text())
    assert manifest['base']==sw.BASE
    assert all(digest(ROOT/n)==h for n,h in manifest['inputs'].items())
    if args.pilot:
        with ThreadPoolExecutor(max_workers=min(4,args.workers)) as pool:
            jobs=[pool.submit(one,'pilot',a,'2011-11-01',[],manifest) for a in ('BASE','OFF','P24','V30')]
            rows=[f.result() for f in jobs]
        for r in rows[:2]: same_nav(EXP/'raw'/r['nav_tag']/'nav.csv',REF/'nav/BASE20111101.csv')
        save('pilot.json',dict(job_id=os.environ['SLURM_JOB_ID'],rows=rows,off_equals_base=True))
        print('PILOT PASS',flush=True);return
    assert json.loads((EXP/'pilot.json').read_text())['off_equals_base']
    arms=[r['arm'] for r in grid()]
    rows=batch('full',arms,[],manifest,args.workers)
    anchor=next(r for r in rows if r['arm']=='BASE' and r['start']=='2011-11-01')
    a=sorted(set(anchor['前五赢家'].split('/'))-{''});assert len(a)==5
    rows+=batch('A',arms,a,manifest,args.workers)
    baseline_days=0
    for r in rows:
        if r['arm']=='BASE': baseline_days+=same_nav(EXP/'raw'/r['nav_tag']/'nav.csv',
            REF/'nav'/('BASE'+r['start'].replace('-','')+('ex5' if r['group']=='A' else '')+'.csv'))
    save('baseline_checks.json',dict(paths=28,exact_nav_rows=baseline_days))
    unions={};sets={}
    for arm in arms[1:]:
        b=set(next(r for r in rows if r['group']=='full' and r['arm']==arm and r['start']=='2011-11-01')['前五赢家'].split('/'))-{''}
        u=tuple(sorted(set(a)|b));unions.setdefault(u,[]).append(arm);sets[arm]=dict(A=a,B=sorted(b),U=list(u))
    save('winner_sets.json',sets)
    executed=len(rows);u_groups={}
    for i,(u,candidates) in enumerate(unions.items(),1):
        group=f'U{i}'; reuse=set(u)==set(a)
        new=([dict(r,group=group) for r in rows if r['group']=='A' and r['arm'] in ['BASE',*candidates]]
             if reuse else batch(group,['BASE',*candidates],list(u),manifest,args.workers))
        rows+=new;executed+=0 if reuse else len(new)
        u_groups[group]=dict(candidates=candidates,codes=list(u),reused_A=reuse)
    for group,excluded in [('full',[]),('A',a)]:
        new=batch(group,['BASE','P24','V30'],excluded,manifest,args.workers,30);rows+=new;executed+=len(new)
    count=validate_groups(rows)
    write('summary_rows.csv',rows)
    assert all(digest(ROOT/n)==h for n,h in manifest['inputs'].items())
    save('verification.json',dict(job_id=os.environ['SLURM_JOB_ID'],executed_paths=executed,
        summary_rows=len(rows),complete_groups=count,baseline_paths=28,baseline_exact_days=baseline_days,
        union_groups=u_groups,negative_cash_days=0,inputs_unchanged=True))
    print('SCAN COMPLETE',executed,'paths',flush=True)


if __name__=='__main__':main()
