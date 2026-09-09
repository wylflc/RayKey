"""Register only the full/A research summaries through the repository's ledger entry point."""
import csv
import json
import os
from prepare import EXP, ROOT, save
from clean_derived_artifacts import write_ledger


def main():
    verification=json.loads((EXP/'analysis_verification.json').read_text())
    assert verification['arms']==53 and verification['refinement_included']
    assert verification['complete_start_and_window_sets'] and verification['negative_cash_days']==0
    rows=[]
    for name in ('summary_rows.csv','refine_rows.csv'):
        with (EXP/name).open() as f:
            rows += [r for r in csv.DictReader(f) if r['group'] in ('full','A')]
    assert len(rows)==53*28
    directory=EXP/'cache/register'
    directory.mkdir(exist_ok=True)
    paths=[]
    for r in rows:
        tag=f"EBOPT20260910_EBOPT{r['arm']}{r['start'].replace('-','')}{'ex5' if r['group']=='A' else ''}"
        path=directory/f'summary_{tag}.csv'
        clean={k:v for k,v in r.items() if k not in ('group','arm','start','nav_tag')}
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(clean),lineterminator='\n');w.writeheader();w.writerow(clean)
        paths.append(path)
    names={p.name for p in paths}
    with os.scandir(directory) as entries:
        update=write_ledger([e for e in entries if e.name in names])
    arms=[r for r in update.arms if r['臂名'].startswith('EBOPT')]
    assert len(arms)==53 and all(r['行数']==28 and r['起点数']==14 for r in arms)
    save('registration.json',dict(rows=len(rows),new_candidates=50,controls=3,arms=arms,
        prefix='EBOPT20260910_EBOPT',entry_point='clean_derived_artifacts.write_ledger',
        production_parameters_changed=False))
    print(f'Registered {len(rows)} full/A summaries, {len(arms)} arms (50 candidates + 3 controls).')


if __name__=='__main__':
    main()
