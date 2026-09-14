"""Frozen-input full/A/U and execution-cost comparisons for OI-186."""
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def save(name, value):
    (EXP/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20), b''): h.update(block)
    return {'bytes':path.stat().st_size, 'sha256':h.hexdigest()}


def prepare():
    prior=json.loads((EXP.parent/'exp_oi179_20260914/manifest.json').read_text())
    flags=shlex.split(sw.BASE)
    relevant={ROOT/p for p in prior['inputs'] if p.startswith('data/raw/') or p.startswith('data/reference/')}
    relevant|={ROOT/flags[flags.index(flag)+1] for flag in ('--universe-file','--daily-states','--hold-states')}
    relevant|={ROOT/p for p in prior['state_args'] if p.endswith('.csv')}
    relevant|={ROOT/'scripts/backtest_valuation_strategy.py',ROOT/'scripts/lot_cooldown.py',ROOT/'scripts/sweep_backtest_configs.py'}
    relevant|=set(EXP.glob('*.py'))|{EXP/'preregister.md'}
    inputs={str(p.relative_to(ROOT)):digest(p) for p in sorted(relevant)}
    for flag in ('--daily-states','--hold-states'):
        for args in (flags,prior['state_args']):
            name=args[args.index(flag)+1]
            assert inputs[name]==prior['inputs'][name], ('equivalence changed',name)
    ends={}
    for code,end in prior['price_ends'].items():
        p=ROOT/f'data/raw/ohlcv/{code}.csv'
        with p.open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',');f.seek(0,2);f.seek(max(0,f.tell()-4096))
            row=next(csv.reader(f.read().decode().splitlines()[-1:]))
        ends[code]=row[header.index('date')]
        assert ends[code]==end, code
    result=dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),job_id=os.getenv('SLURM_JOB_ID'),
                base=sw.BASE,starts=sw.DEFAULT_STARTS,metric=sw.METRIC_VERSION,inputs=inputs,
                state_args=prior['state_args'],production_equivalence=prior['production_equivalence'],price_ends=ends)
    save('manifest.json',result)
    return result


def one(job):
    arm,start,group,bp,excluded=job
    tag=sw.summary_tag(arm+group+str(bp),start,','.join(excluded))
    command=[sys.executable,str(EXP/'engine.py'),*shlex.split(sw.BASE),*manifest['state_args'],
             '--since',start,'--lot-cooldown-start','plan' if arm=='BASE' else 'confirmed',
             '--label-suffix','_'+tag,'--slippage-bp',str(bp),'--out-dir',str(EXP/'cache'),
             '--equity-bond-log-dir',str(EXP/'daily')]
    if excluded:command+=['--exclude-codes',','.join(excluded)]
    if bp==0 and group=='full' and start==sw.EX5_ANCHOR_START:
        command+=['--trade-log',str(EXP/f'ledger_{arm}.csv')]
    with (EXP/'errors'/f'{tag}.txt').open('w') as f:
        p=subprocess.run(command,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=f)
    assert p.returncode==0,(tag,p.returncode)
    with (EXP/'cache'/f'summary_{tag}.csv').open() as f:
        row=next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本']==sw.METRIC_VERSION
    assert row['负现金日数']=='0',(tag,row['负现金日数'])
    return dict(arm=arm,start=start,group=group,bp=bp,tag=tag,**row)


def batch(group,bp,excluded):
    jobs=[(arm,start,group,bp,excluded) for arm in ('BASE','CONF') for start in sw.DEFAULT_STARTS]
    print(f'START {group} {bp}bp {len(jobs)} paths',flush=True)
    with ThreadPoolExecutor(max_workers=24) as pool:rows=list(pool.map(one,jobs))
    with (EXP/f'sweep_{group}_{bp}.txt').open('w') as f:
        f.write(sw.metric_header()+'\n#MARKET|a\n')
        if excluded:f.write('#EX5|fixed|'+','.join(excluded)+'\n')
        for r in rows:
            label=('EX5:' if excluded else '')+r['arm']
            f.write('|'.join([label,r['start']]+[f'{sw._field_value(r,k):.6f}' for k in sw.FIELDS])+'\n')
            f.write(f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n")
    print(f'DONE {group} {bp}bp',flush=True)
    return rows


if __name__=='__main__':
    assert int(os.environ['SLURM_CPUS_PER_TASK'])>=24
    for name in ('cache','nav','stats','errors','daily'):(EXP/name).mkdir(exist_ok=True)
    manifest=prepare()
    smoke=one(('BASE',sw.EX5_ANCHOR_START,'smoke',0,[]))
    with (ROOT/'data/backtest'/f'summary_BASE{sw.EX5_ANCHOR_START.replace("-","")}.csv').open() as f:
        previous=next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs={k:[previous[k],smoke[k]] for k in (*sw.FIELDS,sw.WIN5_KEY) if previous[k]!=smoke[k]}
    save('legacy_reproduction.json',dict(fields=len(sw.FIELDS)+1,differences=diffs))
    assert not diffs,diffs
    rows=batch('full',0,[])
    winners={a:sorted(next(r for r in rows if r['arm']==a and r['start']==sw.EX5_ANCHOR_START)['前五赢家'].split('/')) for a in ('BASE','CONF')}
    A=winners['BASE'];U=sorted(set(A)|set(winners['CONF']))
    save('winners.json',dict(A=A,U=U,by_arm=winners))
    rows+=batch('A',0,A)
    if U!=A:rows+=batch('U',0,U)
    for bp in (10,20,30):
        rows+=batch('full',bp,[])
        rows+=batch('A',bp,A)
        if U!=A:rows+=batch('U',bp,U)
    with (EXP/'summary_rows.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    changed=[p for p,meta in manifest['inputs'].items() if digest(ROOT/p)!=meta]
    assert not changed,changed
    save('completed.json',dict(paths=len(rows)+1,job_id=os.getenv('SLURM_JOB_ID'),unchanged_inputs=True))
