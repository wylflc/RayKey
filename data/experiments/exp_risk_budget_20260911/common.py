import csv
import hashlib
import json
from pathlib import Path
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
REF = EXP.parent/'exp_c030r35_land_20260910'
REVIEW = EXP.parent/'exp_drawdown_review_20260911'
sys.path.insert(0, str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(name, value):
    (EXP/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def write(name, rows):
    path=EXP/name; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1<<20), b''): h.update(chunk)
    return h.hexdigest()


def grid():
    return json.loads((EXP/'grid.json').read_text())


def numeric(row):
    out={k:sw._field_value(row,k) for k in sw.FIELDS}
    out[sw.WIN5_KEY]=sw.parse_window_series(row[sw.WIN5_KEY])
    return out
