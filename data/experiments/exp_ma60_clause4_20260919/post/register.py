"""Register the 11 margin arms' full/A summaries (batch MS4C20260919); BASE is not re-registered."""
import csv
import json
import os
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from clean_derived_artifacts import write_ledger
GRID = json.loads((EXP / 'grid.json').read_text())
CANDIDATES = [g['arm'] for g in GRID if g['arm'] != 'BASE']


def main():
    v = json.loads((EXP / 'verification.json').read_text()); assert v['complete_pairing'] and v['zero_negative_cash']
    with (EXP / 'summary_rows.csv').open() as f:
        rows = [r for r in csv.DictReader(f) if r['group'] in ('full', 'A') and r['arm'] in CANDIDATES]
    assert len(rows) == len(CANDIDATES) * 28
    directory = EXP / 'cache/register'; directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for r in rows:
        tag = f"MS4C20260919_MS{r['arm']}{r['start'].replace('-', '')}{'ex5' if r['group'] == 'A' else ''}"
        path = directory / f'summary_{tag}.csv'
        clean = {k: x for k, x in r.items() if k not in ('group', 'arm', 'start', 'excluded', 'tag')}
        with path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(clean), lineterminator='\n'); w.writeheader(); w.writerow(clean)
        paths.append(path)
    names = {p.name for p in paths}
    with os.scandir(directory) as entries:
        update = write_ledger([e for e in entries if e.name in names])
    arms = [r for r in update.arms if r['臂名'] in {'MS' + a for a in CANDIDATES}]
    assert len(arms) == len(CANDIDATES) and all(int(r['行数']) == 28 and int(r['起点数']) == 14 for r in arms), arms
    (EXP / 'registration.json').write_text(json.dumps(dict(rows=len(rows), candidates=len(CANDIDATES), prefix='MS4C20260919_MS', arms=arms,
        entry_point='clean_derived_artifacts.write_ledger', production_parameters_changed=False), ensure_ascii=False, indent=2) + '\n')
    print(f'Registered {len(rows)} full/A summaries, {len(arms)} arms.')


if __name__ == '__main__':
    main()
