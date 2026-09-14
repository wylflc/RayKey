"""Freeze same-input BASE comparison and verify the reused panel subset."""
import csv
import hashlib
import json
import os
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
LAND=EXP.parent/'exp_oi167_land_20260913'
PRIOR=EXP.parent/'exp_oi174_requal_20260913'
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def save(name,obj):
    (EXP/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


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
        reader=csv.reader(f);head=next(reader);i=head.index('security_code')
        h.update((','.join(head)+'\n').encode())
        for r in reader:
            if codes is None or r[i] in codes:
                h.update((','.join(r)+'\n').encode());n+=1
    return {'sha256':h.hexdigest(),'rows':n}


def main():
    land=json.loads((LAND/'manifest.json').read_text())
    prior=json.loads((PRIOR/'manifest.json').read_text())
    assert land['base']==sw.BASE and land['starts']==sw.DEFAULT_STARTS
    refs=land['registration_reference_inputs'];states=land['registration_state_args']
    current={}
    (EXP/'raw').mkdir(exist_ok=True)
    for name in refs:
        dest=EXP/'raw'/Path(name).name
        shutil.copyfile(ROOT/name,dest)
        current[name]=str(dest.relative_to(ROOT))
    args=shlex.split(sw.BASE)
    import backtest_valuation_strategy as bt
    panel=ROOT/args[args.index('--universe-file')+1]
    codes={c for _,members in bt.load_universe(panel) for c in members}
    subset_codes=set((EXP.parent/'exp_oi168_wc_20260909/codes.txt').read_text().split())
    assert codes<=subset_codes
    equivalence=[]
    for flag in ('--daily-states','--hold-states'):
        sub=ROOT/states[states.index(flag)+1];prod=ROOT/args[args.index(flag)+1]
        a,b=digest(sub),digest(prod,subset_codes);assert a==b,(flag,a,b)
        equivalence.append({'flag':flag,'subset':a,'production':b})
    sources={ROOT/p for p in prior['inputs'] if p.startswith('data/') and (ROOT/p).exists()}
    sources |= set((ROOT/'scripts').glob('*.py')) | set(EXP.glob('*.py'))
    sources |= {EXP/'preregister.md',EXP/'grid.json',ROOT/'data/experiments/exp_selection_edge/candidates.csv',
                ROOT/'scripts/experimental/pv_episode_forward.py',ROOT/'scripts/experimental/moat_param_lab.py',
                ROOT/'scripts/experimental/ex_winner_symmetry_report.py'}
    sources |= {ROOT/p for p in refs.values()} | {ROOT/p for p in states if p.endswith('.csv')}
    sources |= {ROOT/p for p in current.values()}
    frozen=fingerprint(sources)
    for p in refs.values():assert frozen[p]==land['inputs'][p],p
    for code,end in prior['price_ends'].items():
        path=ROOT/f'data/raw/ohlcv/{code}.csv'
        with path.open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',');f.seek(0,2);f.seek(max(0,f.tell()-4096));row=next(csv.reader(f.read().decode().splitlines()[-1:]))
        assert row[header.index('date')]==end,code
    save('manifest.json',{'started_beijing':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         'job_id':os.getenv('SLURM_JOB_ID'),'base':sw.BASE,'starts':sw.DEFAULT_STARTS,'metric':sw.METRIC_VERSION,
         'inputs':frozen,'state_args':states,'production_equivalence':equivalence,'frozen_reference_inputs':refs,
         'current_reference_inputs':current,'price_ends':prior['price_ends'],'arms':6,'candidates':5,'reference_base':'exp_oi167_land_20260913'})
    print('PREPARE COMPLETE: panel subset equivalent; BASE and all inputs frozen.',flush=True)


if __name__=='__main__':main()
