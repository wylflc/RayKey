"""Freeze inputs and verify compact states before submitting any candidate outcomes."""
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
from zoneinfo import ZoneInfo
from policy import EXP, ROOT, grid, ResearchConstraint
sys.path.insert(0, str(ROOT/'scripts'))
import sweep_backtest_configs as sw


def save(name, obj):
    (EXP/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n')


def fingerprint(paths):
    out = {}
    for p in sorted(paths):
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1<<20), b''):
                h.update(block)
        out[str(p.relative_to(ROOT))] = dict(bytes=p.stat().st_size, sha256=h.hexdigest())
    return out


def digest(path, codes=None):
    h = hashlib.sha256()
    n = 0
    with path.open() as f:
        rows = csv.reader(f)
        header = next(rows)
        i = header.index('security_code')
        h.update((','.join(header)+'\n').encode())
        for row in rows:
            if codes is None or row[i] in codes:
                h.update((','.join(row)+'\n').encode())
                n += 1
    return dict(sha256=h.hexdigest(), rows=n)


def main():
    args = shlex.split(sw.BASE)
    prior = json.loads((EXP.parent/'exp_equity_bond_20260909/manifest.json').read_text())
    sources = {ROOT/p for p in prior['inputs'] if p.startswith('data/')}
    sources |= {ROOT/'data/raw/ohlcv/INDEX_000300.csv'}
    sources |= set((ROOT/'scripts').glob('*.py'))
    sources |= {EXP/p for p in ('prepare.py','run.py','engine.py','policy.py','preregister.md','test_policy.py')}
    wc = EXP.parent/'exp_oi168_wc_20260909'
    codes = set((wc/'codes.txt').read_text().split())
    equivalent = []
    state_args = []
    for side, opt in (('base','--daily-states'),('hold','--hold-states')):
        sub = wc/f'val/WCOP/states_{side}.csv'
        prod = ROOT/args[args.index(opt)+1]
        a, b = digest(sub), digest(prod, codes)
        assert a == b, (side, a, b)
        equivalent.append(dict(side=side, subset=a, production=b))
        state_args += [opt, str(sub.relative_to(ROOT))]
    frozen = fingerprint(sources)
    # Changes to production inputs are allowed only after the explicit equivalence check above;
    # record every difference from the earlier experiment instead of silently reusing its hashes.
    changes = [p for p in frozen if p in prior['inputs'] and frozen[p] != prior['inputs'][p]]
    import backtest_valuation_strategy as bt
    panel = ROOT/args[args.index('--universe-file')+1]
    panel_codes = {c for _, members in bt.load_universe(panel) for c in members}
    assert panel_codes <= codes
    ends = {}
    for code in sorted(panel_codes):
        with (ROOT/f'data/raw/ohlcv/{code}.csv').open('rb') as f:
            head = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0,2)
            f.seek(max(0,f.tell()-4096))
            row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        ends[code] = row[head.index('date')]
    save('grid.json', grid())
    audit = []
    for spec in grid():
        obj = ResearchConstraint(ROOT/'data/reference/equity_bond_csi300.csv', mode='cap', metric='spread',
                                 threshold=.03, lower=1., restore_above=True, spec=spec)
        audit.extend(dict(arm=spec['arm'], **row) for row in obj.audit)
    with (EXP/'policy_history.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(audit[0]), lineterminator='\n')
        w.writeheader(); w.writerows(audit)
    save('manifest.json', dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'), base=sw.BASE, starts=sw.DEFAULT_STARTS, metric=sw.METRIC_VERSION,
         inputs=frozen, state_args=state_args, production_equivalence=equivalent, changed_since_prior=changes,
         price_ends=ends, arms=45, new_candidates=42, controls=3, prior_family_arms=19))
    print('PREPARE COMPLETE: inputs frozen; production subset equivalent; 45 arms.', flush=True)


if __name__ == '__main__':
    main()
