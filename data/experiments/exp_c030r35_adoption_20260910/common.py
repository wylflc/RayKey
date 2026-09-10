"""Frozen registry and IO shared by the C030R35 adoption evaluation."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]
PRIOR=EXP.parent/'exp_equity_bond_opt_20260910'
sys.path.insert(0,str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def grid():
    rows=[dict(arm='BASE',family='control',kind='baseline',extra=[]),
          dict(arm='C030R35',family='center',kind='hysteresis',cap=.3,release=.035,extra=[])]
    for cap in (20,25,30,35,40):
        for release in (300,325,350,375,400):
            if cap==30 and release==350:
                continue
            rows.append(dict(arm=f'N{cap:03}R{release}',family='neighborhood',kind='hysteresis',
                             cap=cap/100,release=release/10000,extra=[]))
    for margin in range(10,21):
        if margin==15:
            continue
        for side in ('B','C'):
            r=dict(arm=f'{side}M{margin}',family='margin_control' if side=='B' else 'margin',
                   kind='baseline' if side=='B' else 'hysteresis',extra=['--swap-margin',str(margin/100)])
            if side=='C':
                r.update(cap=.3,release=.035)
            rows.append(r)
    for bp in (10,20,30):
        for side in ('B','C'):
            r=dict(arm=f'{side}S{bp}',family='slip_control' if side=='B' else 'slip',
                   kind='baseline' if side=='B' else 'hysteresis',extra=['--slippage-bp',str(bp)])
            if side=='C':
                r.update(cap=.3,release=.035)
            rows.append(r)
    assert len(rows)==52 and len({r['arm'] for r in rows})==52
    return rows


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write(name,rows):
    with (EXP/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n')
        w.writeheader();w.writerows(rows)


def save(name,obj):
    (EXP/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')


def fingerprint(paths):
    out={}
    for p in sorted(paths):
        h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(1<<20),b''):
                h.update(block)
        out[str(p.relative_to(ROOT))]=dict(bytes=p.stat().st_size,sha256=h.hexdigest())
    return out
