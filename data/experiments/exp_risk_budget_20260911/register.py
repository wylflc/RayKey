"""Register completed unique formal summaries via the repository ledger writer."""
import csv
import json
from types import SimpleNamespace
from common import EXP, read, save, digest
import clean_derived_artifacts as clean


def canonical(rows):
    return {(r.get('扫描标签'),r.get('策略'),r.get('计量版本') or 'm1'):
            {k:v for k,v in r.items() if k is not None and v not in ('',None)} for r in rows}


def main():
    verification=json.loads((EXP/'verification.json').read_text())
    audit=json.loads((EXP/'execution_checks.json').read_text())
    assert audit['negative_cash_days']==0 and audit['inputs_unchanged']
    tags=sorted({r['nav_tag'] for r in read(EXP/'summary_rows.csv')})
    assert len(tags)==verification['executed_paths']==audit['executed_paths']
    assert not any('pilot' in t or 'RBOFF' in t for t in tags)
    files=[]
    for tag in tags:
        p=EXP/'raw'/tag/f'summary_{tag}.csv'
        assert p.exists()
        rows=read(p);assert len(rows)==1 and rows[0]['计量版本']=='m3'
        files.append(SimpleNamespace(name=p.name,path=str(p)))
    old=canonical(read(clean.MERGED));archive_hash=digest(clean.ARCHIVED_LEDGER)
    preview=clean.write_ledger(files,apply=False)
    proposed=canonical(preview.current)
    assert all(proposed[k]==v for k,v in old.items()), 'would change an existing summary'
    result=clean.write_ledger(files,apply=True)
    after=canonical(read(clean.MERGED))
    assert all(after[k]==v for k,v in old.items())
    assert digest(clean.ARCHIVED_LEDGER)==archive_hash
    arm_names=sorted({clean.arm_name(tag)[0] for tag in tags})
    note=dict(formal_paths=len(tags),before_current_rows=len(old),after_current_rows=len(after),
        new_keys=len(after.keys()-old.keys()),existing_rows_preserved=True,archive_unchanged=True,
        registered_arm_names=arm_names,registered_arm_count=len(arm_names),
        economic_candidates=12,baseline=1,excluded_pilot_and_off=True)
    # Keep the first successful registration's before/after evidence on reruns.
    if not (EXP/'registration.json').exists():save('registration.json',note)
    print('REGISTERED',len(tags),'paths;',len(arm_names),'ledger arm names;',note['new_keys'],'new keys')


if __name__=='__main__':main()
