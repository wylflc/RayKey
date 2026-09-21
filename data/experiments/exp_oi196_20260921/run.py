"""OI-196: OLD (pre-fix snapshot inputs) vs NEW (fixed production inputs), same engine and BASE. 14 starts, full/A/U, 0bp."""
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
OLD = EXP / 'old_inputs'
PANEL = OLD / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
PROD_INPUTS = ['scripts/backtest_valuation_strategy.py', 'scripts/corporate_actions.py', 'scripts/sweep_backtest_configs.py',
               'data/reference/equity_bond_csi300.csv', 'data/reference/cost_of_equity_inputs.csv',
               'data/raw/corporate_actions/a_share_corporate_actions.csv']


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def prepare():
    inputs = {p: digest(ROOT / p) for p in PROD_INPUTS}
    inputs |= {str(p.relative_to(ROOT)): digest(p) for p in EXP.glob('*.py')}
    inputs |= {str(p.relative_to(ROOT)): digest(p) for p in [PANEL, EXP/'actions_corrected.csv']}
    for arm in ('OLD','NEW'):
        for name in ('a_share_daily_states_adopted.csv','a_share_daily_states_hold.csv'):
            p=EXP/'states'/arm/name
            inputs[str(p.relative_to(ROOT))]=digest(p)
    manifest = dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, starts=sw.DEFAULT_STARTS,
                    metric=sw.METRIC_VERSION, inputs=inputs,
                    extraction=json.loads((EXP/'state_extracts.json').read_text()))
    save('manifest.json', manifest)
    return manifest


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    command = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), '--since', start, '--label-suffix', '_' + tag,
               '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily')]
    env = dict(os.environ)
    command += ['--universe-file', str(PANEL), '--daily-states', str(EXP/'states'/arm/'a_share_daily_states_adopted.csv'),
                '--hold-states', str(EXP/'states'/arm/'a_share_daily_states_hold.csv')]
    env['EXP_ARM'] = arm
    env['EXP_ACTIONS_FILE'] = str(OLD/'data/raw/corporate_actions/a_share_corporate_actions.csv' if arm=='OLD' else EXP/'actions_corrected.csv')
    if excluded:
        command += ['--exclude-codes', ','.join(excluded)]
    if group == 'full' and start == sw.EX5_ANCHOR_START:
        command += ['--trade-log', str(EXP / f'ledger_{arm}.csv')]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=env)
    assert p.returncode == 0, (tag, p.returncode)
    with (EXP / 'cache' / f'summary_{tag}.csv').open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION
    assert row['负现金日数'] == '0', (tag, row['负现金日数'])
    return dict(arm=arm, start=start, group=group, bp=0, tag=tag, **row)


def batch(group, excluded):
    jobs = [(arm, start, group, excluded) for arm in ('OLD', 'NEW') for start in sw.DEFAULT_STARTS]
    print(f'START {group} {len(jobs)} paths', flush=True)
    with ThreadPoolExecutor(max_workers=16) as pool:
        rows = list(pool.map(one, jobs))
    with (EXP / f'sweep_{group}.txt').open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for r in rows:
            label = ('EX5:' if excluded else '') + r['arm']
            f.write('|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n")
    print(f'DONE {group}', flush=True)
    return rows


if __name__ == '__main__':
    assert int(os.environ['SLURM_CPUS_PER_TASK']) >= 24
    for name in ('cache', 'nav', 'stats', 'errors', 'daily'):
        (EXP / name).mkdir(exist_ok=True)
    manifest = prepare()
    smoke = one(('OLD', sw.EX5_ANCHOR_START, 'smoke', []))
    with (ROOT / 'data/backtest' / f'summary_BASE{sw.EX5_ANCHOR_START.replace("-", "")}.csv').open() as f:
        previous = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs = {k: [previous[k], smoke[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if previous[k] != smoke[k]}
    save('legacy_reproduction.json', dict(fields=len(sw.FIELDS) + 1, differences=diffs))
    assert not diffs, diffs
    rows = batch('full', [])
    winners = {a: sorted(next(r for r in rows if r['arm'] == a and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/')) for a in ('OLD', 'NEW')}
    A = winners['OLD']; U = sorted(set(A) | set(winners['NEW']))
    save('winners.json', dict(A=A, U=U, by_arm=winners))
    rows += batch('A', A)
    if U != A:
        rows += batch('U', U)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    changed = [p for p, meta in manifest['inputs'].items() if digest(ROOT / p) != meta]
    assert not changed, changed
    save('completed.json', dict(paths=len(rows) + 1, job_id=os.getenv('SLURM_JOB_ID'), unchanged_inputs=True))
