"""Archive validated summaries through the repository's single ledger writer."""
import csv
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import clean_derived_artifacts as archive
import sweep_backtest_configs as sw


def main():
    verification=json.loads((EXP/'verification.json').read_text())
    assert verification['inputs_unchanged']
    with (EXP/'summary_rows.csv').open() as f:rows=list(csv.DictReader(f))
    files=[]
    with tempfile.TemporaryDirectory(prefix='raykey_eb_ledger_') as temp:
        for row in rows:
            group,arm,start=row['group'],row['arm'],row['start']
            tag=sw.summary_tag(arm,start,'fixed' if group!='full' else '')
            batch=f"EB{'LOW' if EXP.name=='high_base' else 'CAP'}{group.replace('_','')}20260909"
            name=f'summary_{batch}_{tag}.csv'
            path=Path(temp)/name
            payload={k:v for k,v in row.items() if k not in ('group','arm','start')}
            with path.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(payload),lineterminator='\n');w.writeheader();w.writerow(payload)
            files.append(SimpleNamespace(path=path,name=name))
        update=archive.write_ledger(files)
    arms=[r for r in update.arms if r['臂名'].startswith('EB')]
    result={'registered_rows':len(rows),'ledger_rows_from_this_batch':update.current_added,
            'candidate_and_control_arm_count':len(arms),'arms':[r['臂名'] for r in arms]}
    (EXP/'ledger_registration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result)


if __name__=='__main__':main()
