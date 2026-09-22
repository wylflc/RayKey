"""Freeze BASE inputs and stream exact panel subsets; audit price end dates."""
import csv
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<22),b''): h.update(block)
    return dict(bytes=path.stat().st_size,sha256=h.hexdigest())


def main():
    assert not (EXP/'manifest.json').exists(), 'Inputs already frozen; do not overwrite'
    for folder in ('inputs','cache','nav','stats','errors','daily'):(EXP/folder).mkdir(exist_ok=True)
    panel='data/processed/pit_attention/panel_moat_bank_v6b.csv'
    with (ROOT/panel).open(newline='') as f: codes={r['security_code'] for r in csv.DictReader(f)}
    paths=[panel,'data/reference/cost_of_equity_inputs.csv','data/reference/equity_bond_csi300.csv',
        'data/reference/a_share_exright_terms.csv','data/raw/corporate_actions/a_share_corporate_actions.csv',
        'data/raw/a_share_delisted_roster.csv','data/processed/a_share_watchlist_quality_tiers.csv']
    paths += ['data/raw/ohlcv/'+c+'.csv' for c in sorted(codes) if (ROOT/'data/raw/ohlcv'/f'{c}.csv').exists()]
    paths += [str(p.relative_to(ROOT)) for p in sorted((ROOT/'data/raw/ohlcv').glob('INDEX_*.csv'))]
    inputs={}; price_ends={}
    for name in paths:
        src=ROOT/name; dst=EXP/'inputs'/name; dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dst)
        inputs[name]=digest(dst)
        assert inputs[name]==digest(src),name
        if name.startswith('data/raw/ohlcv/'):
            with dst.open() as f:
                next(f); end=''
                for line in f:
                    if line.strip():end=line.split(',',1)[0]
            price_ends[dst.stem]=end
    extracted={}
    for name in ('a_share_daily_states_adopted.csv','a_share_daily_states_hold.csv'):
        src=ROOT/'data/processed'/name; dst=EXP/'inputs/data/processed'/name
        initial=src.stat(); h=hashlib.sha256(); sub=hashlib.sha256(); count=0; selected=0; seen=set()
        with src.open('rb') as f,dst.open('wb') as out:
            header=next(f); assert header.split(b',')[0]==b'security_code'
            h.update(header);sub.update(header);out.write(header)
            for line in f:
                h.update(line);count+=1
                code=line.split(b',',1)[0].decode()
                if code in codes:
                    selected+=1;seen.add(code);sub.update(line);out.write(line)
        assert (initial.st_size,initial.st_mtime_ns)==(src.stat().st_size,src.stat().st_mtime_ns),src
        assert digest(dst)['sha256']==sub.hexdigest()
        extracted[name]=dict(source_sha256=h.hexdigest(),source_rows=count,subset_rows=selected,
                             subset_sha256=sub.hexdigest(),missing_panel_codes=sorted(codes-seen))
        # A panel member can have no production state (e.g. insufficient history).
        # This is a source-coverage limitation shared by BASE, not a dropped row.
        # All existing source rows for panel members were copied verbatim above.
        if codes-seen: print('Panel members absent from source',name,sorted(codes-seen),flush=True)
        inputs['data/processed/'+name]=digest(dst)
        print('Exact panel extraction',name,selected,'/',count,flush=True)
    code_files=['scripts/backtest_valuation_strategy.py','scripts/sweep_backtest_configs.py',
        'scripts/corporate_actions.py','scripts/equity_bond_constraint.py','scripts/swap_chop_guard.py']
    code_hashes={p:digest(ROOT/p) for p in code_files}
    for p in EXP.glob('*.py'): code_hashes[str(p.relative_to(ROOT))]=digest(p)
    manifest=dict(created_at_utc=datetime.now(timezone.utc).isoformat(),job_id=os.getenv('SLURM_JOB_ID'),
        base=sw.BASE,starts=sw.DEFAULT_STARTS,metric=sw.METRIC_VERSION,
        inputs=inputs,code_hashes=code_hashes,panel_codes=sorted(codes),extraction=extracted,
        price_end_dates=price_ends,price_end_distribution=dict(Counter(price_ends.values())),
        missing_price_codes=sorted(c for c in codes if c not in price_ends),
        history_refreshed=False)
    (EXP/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('Frozen',len(inputs),'inputs; price ends',manifest['price_end_distribution'],flush=True)


if __name__=='__main__': main()
