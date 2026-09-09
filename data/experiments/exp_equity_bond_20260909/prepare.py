"""Freeze current formal baseline and verify compact states against full production inputs."""
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
from zoneinfo import ZoneInfo
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
PRIOR=EXP.parent/'exp_buy_fraction_operating_20260909'
WCEXP=EXP.parent/'exp_oi168_wc_20260909'
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def save(name,value):
    (EXP/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def fingerprint(paths):
    out={}
    for p in sorted(paths):
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1<<20),b''):h.update(block)
        out[str(p.relative_to(ROOT))]={'bytes':p.stat().st_size,'sha256':h.hexdigest()}
    return out


def digest(path,codes=None):
    h=hashlib.sha256();n=0
    with path.open() as f:
        reader=csv.reader(f);header=next(reader);i=header.index('security_code')
        h.update((','.join(header)+'\n').encode())
        for row in reader:
            if codes is None or row[i] in codes:
                h.update((','.join(row)+'\n').encode());n+=1
    return {'sha256':h.hexdigest(),'rows':n}


def main():
    args=shlex.split(sw.BASE)
    states=WCEXP/'val/WCOP/states_base.csv';hold=WCEXP/'val/WCOP/states_hold.csv'
    state_args=f'--daily-states {states.relative_to(ROOT)} --hold-states {hold.relative_to(ROOT)}'
    data='data/reference/equity_bond_csi300.csv'
    common=f'{state_args} --equity-bond-data {data}'
    grid=[{'arm':'BASE','kind':'baseline','args':state_args}]
    def arm(name,kind,opts):grid.append({'arm':name,'kind':kind,'args':common+' '+opts})
    for n in (160,100):arm(f'EBFIX{n}','fixed',f'--equity-bond-mode cap --equity-bond-metric spread --equity-bond-lower {n/100} --equity-bond-upper {n/100}')
    for q in (20,30,40):arm(f'EBQ{q}','percentile',f'--equity-bond-mode cap --equity-bond-threshold {q/100}')
    for s in (2,3,4):arm(f'EBS{s:02}','spread',f'--equity-bond-mode cap --equity-bond-metric spread --equity-bond-threshold {s/100}')
    arm('EBCR30','credit','--equity-bond-mode credit --equity-bond-threshold .3')
    for q in (10,20,30):arm(f'EBR{q}','ramp',f'--equity-bond-mode ramp --equity-bond-lower 0 --equity-bond-threshold {q/100} --equity-bond-ramp-high {1-q/100}')
    save('grid.json',grid)
    (EXP/'configs.txt').write_text('\n'.join(f"{r['arm']}|{r['args']}" for r in grid)+'\n')
    with (PRIOR/'summary_rows.csv').open() as f:
        registered=[r for r in csv.DictReader(f) if r['arm']=='BASE' and r['group'] in ('full','A')]
    assert len(registered)==28
    for r in registered:r['扫描标签']=sw.summary_tag('BASE',r['start'],'fixed' if r['group']=='A' else '')
    with (EXP/'baseline_before.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(registered[0]),lineterminator='\n');w.writeheader();w.writerows(registered)
    prior=json.loads((PRIOR/'manifest.json').read_text())
    sources={ROOT/name for name in prior['inputs'] if name.startswith(('data/raw/','data/reference/','data/processed/','data/interim/','data/experiments/exp_oi168_wc_20260909/'))}
    sources.update((ROOT/'scripts').glob('*.py'))
    sources|={ROOT/data,ROOT/'data/raw/macro/csi300_pe_ttm.csv',ROOT/'data/raw/macro/china_10y_yield_daily.csv'}
    sources|={EXP/name for name in ('prepare.py','run.py','scan.py','configs.txt','grid.json','preregister.md','baseline_before.csv')}
    before=fingerprint(sources)
    for name in sources:
        rel=str(name.relative_to(ROOT))
        if rel in prior['inputs'] and rel.startswith('data/'):
            assert before[rel]==prior['inputs'][rel],f'Source changed since last scan: {rel}'
    import backtest_valuation_strategy as bt
    panel=ROOT/args[args.index('--universe-file')+1]
    codes={c for _,members in bt.load_universe(panel) for c in members};ends={}
    for code in codes:
        path=ROOT/f'data/raw/ohlcv/{code}.csv'
        with path.open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0,2);f.seek(max(0,f.tell()-4096));row=next(csv.reader(f.read().decode().splitlines()[-1:]))
        end=row[header.index('date')];ends[end]=ends.get(end,0)+1
    all_codes=set((WCEXP/'codes.txt').read_text().split());eq=[]
    for sub,opt in ((states,'--daily-states'),(hold,'--hold-states')):
        a=digest(sub);b=digest(ROOT/args[args.index(opt)+1],all_codes);assert a==b
        eq.append({'side':sub.name,'subset':a,'production':b,'equal':True})
    save('production_equivalence.json',eq)
    save('manifest.json',{'started_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'job_id':os.environ.get('SLURM_JOB_ID'),
          'base':sw.BASE,'starts':sw.DEFAULT_STARTS,'metric':sw.METRIC_VERSION,'inputs':before,'price_ends':ends,'candidate_count':10,'known_nonbase_controls':2})
    unchanged=fingerprint(sources)==before
    save('prepare_verification.json',{'inputs_unchanged':unchanged,'equivalence':eq});assert unchanged
    print('PREPARE COMPLETE: 13 arms; production equivalence and input hashes verified.',flush=True)


if __name__=='__main__':main()
