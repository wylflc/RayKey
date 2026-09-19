"""MA60_1 clause-4 supplements: swap-margin scan (11 arms) with full/A/U, and winner-exclusion dose curve K1/K3/K5/K10."""
import argparse
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
GRID = json.loads((EXP / 'grid.json').read_text())
ARMS = [g['arm'] for g in GRID]
MARGIN = {g['arm']: g['margin'] for g in GRID}
DOSE_ARMS = ['BASE', 'MA60_1M15']
INPUTS = ['data/processed/pit_attention/panel_moat_bank_v6b.csv', 'data/processed/a_share_daily_states_adopted.csv',
          'data/processed/a_share_daily_states_hold.csv', 'data/raw/corporate_actions/a_share_corporate_actions.csv',
          'data/reference/equity_bond_csi300.csv', 'data/reference/cost_of_equity_inputs.csv',
          'scripts/backtest_valuation_strategy.py', 'scripts/lot_cooldown.py', 'scripts/sweep_backtest_configs.py']


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def prepare():
    inputs = {p: digest(ROOT / p) for p in INPUTS}
    inputs |= {str(p.relative_to(ROOT)): digest(p) for p in sorted(EXP.glob('*.py')) + [EXP / 'preregister.md', EXP / 'grid.json']}
    manifest = dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), job_id=os.getenv('SLURM_JOB_ID'),
                    base=sw.BASE, starts=sw.DEFAULT_STARTS, metric=sw.METRIC_VERSION, inputs=inputs, grid=GRID)
    save('manifest.json', manifest)
    return manifest


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    command = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), '--slope-arm', arm, '--since', start,
               '--label-suffix', '_' + tag, '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily')]
    if arm != 'BASE':
        command += ['--swap-margin', f'{MARGIN[arm]:.2f}']
    if excluded:
        command += ['--exclude-codes', ','.join(excluded)]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f)
    assert p.returncode == 0, (tag, p.returncode, (EXP / 'errors' / f'{tag}.txt').read_text()[-1500:])
    with (EXP / 'cache' / f'summary_{tag}.csv').open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION
    assert row['负现金日数'] == '0', (tag, row['负现金日数'])
    return dict(arm=arm, start=start, group=group, excluded='/'.join(excluded), tag=tag, **row)


def batch(group, arms, excluded, workers):
    jobs = [(arm, start, group, excluded) for arm in arms for start in sw.DEFAULT_STARTS]
    print(f'START {group} {len(jobs)} paths excluded={excluded}', flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            rows.append(f.result())
    rows.sort(key=lambda r: (arms.index(r['arm']), r['start']))
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


def ranking(tag):
    contrib = json.loads((EXP / 'contrib' / f'{tag}.json').read_text())
    return [c for c, v in sorted(contrib.items(), key=lambda kv: (-kv[1], kv[0])) if v > 0]


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--workers', type=int, default=48); args = ap.parse_args()
    assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers))
    manifest = prepare()
    smoke = one(('BASE', sw.EX5_ANCHOR_START, 'smoke', []))
    with (ROOT / 'data/backtest' / f'summary_BASE{sw.EX5_ANCHOR_START.replace("-", "")}.csv').open() as f:
        previous = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs = {k: [previous[k], smoke[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if previous[k] != smoke[k]}
    save('legacy_reproduction.json', dict(fields=len(sw.FIELDS) + 1, differences=diffs))
    assert not diffs, diffs
    rows = batch('full', ARMS, [], args.workers)
    anchor = next(r for r in rows if r['arm'] == 'BASE' and r['start'] == sw.EX5_ANCHOR_START)
    rank = ranking(anchor['tag'])
    A = sorted(rank[:5])
    assert A == sorted(anchor['前五赢家'].split('/')), (A, anchor['前五赢家'])
    assert len(rank) >= 10, rank
    doses = {'K1': sorted(rank[:1]), 'K3': sorted(rank[:3]), 'K5': A, 'K10': sorted(rank[:10])}
    winner_sets, unions = {}, {}
    for arm in ARMS[1:]:
        b = sorted(next(r for r in rows if r['arm'] == arm and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
        u = tuple(sorted(set(A) | set(b)))
        winner_sets[arm] = dict(A=A, B=b, U=list(u))
        unions.setdefault(u, []).append(arm)
    save('winners.json', dict(A=A, ranking=rank, doses=doses, winner_sets=winner_sets))
    rows += batch('A', ARMS, A, args.workers)
    union_groups = {}
    for i, (u, arms_in) in enumerate(unions.items(), 1):
        group = f'U{i}'
        reuse = list(u) == A
        if reuse:
            rows += [dict(r, group=group) for r in rows if r['group'] == 'A' and r['arm'] in ['BASE', *arms_in]]
        else:
            rows += batch(group, ['BASE', *arms_in], list(u), args.workers)
        union_groups[group] = dict(codes=list(u), candidates=arms_in, reused_A=reuse)
    for k in ('K1', 'K3', 'K10'):
        rows += batch(k, DOSE_ARMS, doses[k], args.workers)
    rows += [dict(r, group='K5') for r in rows if r['group'] == 'A' and r['arm'] in DOSE_ARMS]
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); w.writeheader(); w.writerows(rows)
    changed = [p for p, meta in manifest['inputs'].items() if digest(ROOT / p) != meta]
    assert not changed, changed
    executed = sum(1 for r in rows if not (r['group'].startswith('U') and union_groups[r['group']]['reused_A']) and r['group'] != 'K5') + 1
    save('completed.json', dict(executed_paths=executed, rows=len(rows), job_id=os.getenv('SLURM_JOB_ID'), unchanged_inputs=True, union_groups=union_groups))
    print(f'SCAN COMPLETE {executed} paths / {len(rows)} rows', flush=True)
