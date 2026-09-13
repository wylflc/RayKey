"""Freeze inputs, re-verify the compact state subset, require the landed OI-167 BASE, and register the 8-arm grid."""
import csv
import hashlib
import json
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PRIOR = EXP.parent / 'exp_equity_bond_opt_20260910'
LAND = EXP.parent / 'exp_oi167_land_20260913'
sys.path.insert(0, str(PRIOR))
sys.path.insert(0, str(ROOT / 'scripts'))
from policy import ResearchConstraint  # noqa: E402
import sweep_backtest_configs as sw  # noqa: E402

ARMS = ['BASE', 'C100R35', 'C100R40', 'CONFIRM2', 'CONFIRM3', 'TREND10', 'TREND12', 'C030R45']


def save(name, obj):
    (EXP / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')


def fingerprint(paths):
    out = {}
    for p in sorted(paths):
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''):
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
        h.update((','.join(header) + '\n').encode())
        for row in rows:
            if codes is None or row[i] in codes:
                h.update((','.join(row) + '\n').encode())
                n += 1
    return dict(sha256=h.hexdigest(), rows=n)


def main():
    args = shlex.split(sw.BASE)
    prior = json.loads((PRIOR / 'manifest.json').read_text())
    sources = {ROOT / p for p in prior['inputs'] if p.startswith('data/') and (ROOT / p).exists()}
    sources |= set((ROOT / 'scripts').glob('*.py')) | {PRIOR / 'policy.py'}
    sources |= {EXP / p for p in ('prepare.py', 'run.py', 'engine.py', 'analyze.py', 'register.py', 'preregister.md', 'grid.json')}
    wc = EXP.parent / 'exp_oi168_wc_20260909'
    codes = set((wc / 'codes.txt').read_text().split())
    land = json.loads((LAND / 'verification.json').read_text())
    assert land['track_a_pass'] and land['base_paths'] == 28
    land_manifest = json.loads((LAND / 'manifest.json').read_text())
    # 与 OI-167 登记运行完全相同的输入：当前生产状态的面板子集（逐行 digest 再核一次）＋冻结的当前参考表
    state_args = land_manifest['registration_state_args']
    equivalent = []
    for side, opt in (('base', '--daily-states'), ('hold', '--hold-states')):
        sub = ROOT / state_args[state_args.index(opt) + 1]
        prod = ROOT / args[args.index(opt) + 1]
        a, b = digest(sub), digest(prod, codes)
        assert a == b, (side, a, b)
        equivalent.append(dict(side=side, subset=a, production=b))
    frozen_refs = {k: ROOT / v for k, v in land_manifest['registration_reference_inputs'].items()}
    for name, path in frozen_refs.items():
        assert fingerprint({path})[str(path.relative_to(ROOT))] == land_manifest['inputs'][str(path.relative_to(ROOT))], name
    sources |= set(frozen_refs.values()) | {ROOT / v for v in state_args if v.endswith('.csv')}
    frozen = fingerprint(sources)
    changes = [p for p in frozen if p in prior['inputs'] and frozen[p] != prior['inputs'][p]]
    assert frozen[str((PRIOR / 'policy.py').relative_to(ROOT))] == prior['inputs'][str((PRIOR / 'policy.py').relative_to(ROOT))]
    import backtest_valuation_strategy as bt
    panel = ROOT / args[args.index('--universe-file') + 1]
    panel_codes = {c for _, members in bt.load_universe(panel) for c in members}
    assert panel_codes <= codes
    for code, end in prior['price_ends'].items():
        with (ROOT / f'data/raw/ohlcv/{code}.csv').open('rb') as f:
            head = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0, 2); f.seek(max(0, f.tell() - 4096))
            row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        assert row[head.index('date')] == end, code
    specs = json.loads((EXP / 'grid.json').read_text())
    assert [r['arm'] for r in specs] == ARMS
    audit = []
    for spec in specs:
        obj = ResearchConstraint(frozen_refs['data/reference/equity_bond_csi300.csv'], mode='cap', metric='spread',
                                 threshold=.03, lower=.3, restore_above=True, release_threshold=.035, spec=spec)
        audit.extend(dict(arm=spec['arm'], **row) for row in obj.audit)
    with (EXP / 'policy_history.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(audit[0]), lineterminator='\n')
        w.writeheader(); w.writerows(audit)
    save('manifest.json', dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'), base=sw.BASE, starts=sw.DEFAULT_STARTS, metric=sw.METRIC_VERSION,
         inputs=frozen, state_args=state_args, production_equivalence=equivalent, changed_since_prior=changes,
         frozen_reference_inputs={k: str(v.relative_to(ROOT)) for k, v in frozen_refs.items()},
         price_ends=prior['price_ends'], arms=len(ARMS), candidates=len(ARMS) - 1, reference_base='exp_oi167_land_20260913',
         landed_base_job=land['job_id']))
    print('PREPARE COMPLETE: inputs frozen; production subset equivalent; landed BASE present; 8 arms.', flush=True)


if __name__ == '__main__':
    main()
