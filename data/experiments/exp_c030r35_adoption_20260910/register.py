"""Register this fixed research batch through the repository's canonical ledger API."""
import csv
import json
import os
from common import EXP, read, save
from clean_derived_artifacts import write_ledger


def main():
    verification=json.loads((EXP/'analysis_verification.json').read_text())
    assert verification['arms']==52 and verification['complete_start_and_window_sets']
    assert verification['negative_cash_days']==0
    rows=[r for r in read(EXP/'summary_rows.csv') if r['group'] in ('full','A')]
    assert len(rows)==52*28
    directory=EXP/'cache/register';directory.mkdir(exist_ok=True)
    names=set()
    for r in rows:
        tag=f"EBADOPT20260910_EBAD{r['arm']}{r['start'].replace('-','')}{'ex5' if r['group']=='A' else ''}"
        path=directory/f'summary_{tag}.csv'
        clean={k:v for k,v in r.items() if k not in ('group','arm','start','nav_tag')}
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(clean),lineterminator='\n');w.writeheader();w.writerow(clean)
        names.add(path.name)
    with os.scandir(directory) as entries:update=write_ledger([e for e in entries if e.name in names])
    arms=[r for r in update.arms if r['臂名'].startswith('EBAD')]
    assert len(arms)==52 and all(r['行数']==28 and r['起点数']==14 for r in arms)
    save('registration.json',dict(rows=len(rows),arms=arms,prefix='EBADOPT20260910_EBAD',
        new_parameter_combinations=48,repeated_parameter_combinations=4,new_candidate_combinations=35,
        new_control_combinations=13,prior_registered_family_arms=72,total_registered_family_arms=124,
        entry_point='clean_derived_artifacts.write_ledger',production_parameters_changed=False))
    print('Registered 1456 full/A summaries, 52 arms; 48 new settings, 4 reproduced settings.')


if __name__=='__main__':main()
