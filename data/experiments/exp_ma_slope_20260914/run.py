"""All preregistered full/A/U paths for the 6-arm slope comparison, with BASE reproduction against the landed OI-167 BASE."""
import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from prepare import EXP, ROOT, LAND, fingerprint, save, sw


def one(job):
    group, arm, start, excluded, states, resume = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cache = EXP / 'cache' / group
    cache.mkdir(parents=True, exist_ok=True)
    summary = cache / f'summary_{tag}.csv'
    if not resume or not summary.exists():
        refs = json.loads((EXP / 'manifest.json').read_text())['frozen_reference_inputs']
        command = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *states,
                   '--slope-arm', arm, '--since', start, '--label-suffix', '_' + tag,
                   '--out-dir', str(cache), '--equity-bond-log-dir', str(EXP / 'daily' / group),
                   '--equity-bond-data', refs['data/reference/equity_bond_csi300.csv']]
        if group == 'full' and arm in ('BASE', 'BOTH1') and start in ('2009-11-01', '2011-11-01'):
            if '--no-artifacts' in command:
                command.remove('--no-artifacts')
            output = EXP / 'signals' / arm / start
            output.mkdir(parents=True, exist_ok=True)
            command += ['--candidate-log', str(output / 'candidates.csv'), '--trade-log', str(output / 'ledger.csv')]
        if excluded:
            command += ['--exclude-codes', ','.join(excluded)]
        env = dict(os.environ, RAYKEY_ACTIONS=str(ROOT / refs['data/raw/corporate_actions/a_share_corporate_actions.csv']),
                   RAYKEY_RATES=str(ROOT / refs['data/reference/cost_of_equity_inputs.csv']))
        error = EXP / 'errors' / f'{tag}.txt'
        error.parent.mkdir(exist_ok=True)
        with error.open('w') as f:
            result = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=env)
        if result.returncode:
            raise RuntimeError(f'{tag} exit {result.returncode}: {error.read_text()[-3000:]}')
    with summary.open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION
    assert row['负现金日数'] == '0', (tag, row['负现金日数'])
    assert (EXP / 'nav' / f'{tag}.csv').exists()
    return dict(group=group, arm=arm, start=start, nav_tag=tag, **row)


def batch(group, arms, excluded, args, manifest):
    jobs = [(group, arm, start, excluded, manifest['state_args'], args.resume) for arm in arms for start in sw.DEFAULT_STARTS]
    rows = []
    print(f'{group} START {len(jobs)} paths, excluded={excluded}', flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(one, j) for j in jobs]):
            rows.append(f.result())
            if len(rows) % 28 == 0:
                print(f'{group} {len(rows)}/{len(jobs)}', flush=True)
    rows.sort(key=lambda r: (arms.index(r['arm']), r['start']))
    with (EXP / f'sweep_{group}.txt').open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for row in rows:
            label = ('EX5:' if excluded else '') + row['arm']
            f.write('|'.join([label, row['start']] + [f'{sw._field_value(row, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{row['start']}|{row[sw.WIN5_KEY]}\n")
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workers', type=int, default=48)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--smoke', action='store_true')
    args = p.parse_args()
    assert args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', args.workers))
    manifest = json.loads((EXP / 'manifest.json').read_text())
    assert manifest['base'] == sw.BASE and manifest['starts'] == sw.DEFAULT_STARTS
    assert fingerprint({ROOT / p for p in manifest['inputs']}) == manifest['inputs']
    labels = [r['arm'] for r in json.loads((EXP / 'grid.json').read_text())]
    landed = sw.load_scan(LAND / 'sweep_base.txt')[0]
    a = sorted(json.loads((LAND / 'guardrail.json').read_text())['winners_new'])
    if args.smoke:
        import time
        began = time.monotonic()
        rows = [one(('full', arm, sw.EX5_ANCHOR_START, [], manifest['state_args'], False)) for arm in ('BASE', 'BOTH1')]
        old = landed['']['BASE'][sw.EX5_ANCHOR_START]
        for key in sw.FIELDS:
            assert float(f'{sw._field_value(rows[0], key):.6f}') == old[key], key
        save('smoke.json', dict(elapsed_seconds=time.monotonic()-began, baseline_fields_reproduced=len(sw.FIELDS),
                               job_id=os.environ.get('SLURM_JOB_ID'), rows=[dict(arm=r['arm'], cagr=r['年化']) for r in rows]))
        print('SMOKE COMPLETE: native BASE reproduced; candidate ran; no negative cash.', flush=True)
        return
    full = batch('full', labels, [], args, manifest)
    anchor = next(r for r in full if r['arm'] == 'BASE' and r['start'] == sw.EX5_ANCHOR_START)
    assert sorted(set(anchor['前五赢家'].split('/')) - {''}) == a, (anchor['前五赢家'], a)
    rows = full + batch('A', labels, a, args, manifest)
    checks = 0
    for row in rows:
        if row['arm'] != 'BASE':
            continue
        old = landed['' if row['group'] == 'full' else 'EX5:']['BASE'][row['start']]
        for key in sw.FIELDS:
            now = float(f'{sw._field_value(row, key):.6f}')
            assert now == old[key], (row['group'], row['start'], key, now, old[key])
            checks += 1
        assert sw.parse_window_series(row[sw.WIN5_KEY]) == old[sw.WIN5_KEY]
    unions, winner_sets, union_groups = {}, {}, {}
    for arm in labels[1:]:
        anchor = next(r for r in full if r['arm'] == arm and r['start'] == sw.EX5_ANCHOR_START)
        b = set(anchor['前五赢家'].split('/')) - {''}
        assert len(b) == 5
        u = tuple(sorted(set(a) | b))
        unions.setdefault(u, []).append(arm)
        winner_sets[arm] = dict(A=a, B=sorted(b), U=list(u))
    save('winner_sets.json', winner_sets)
    executed = len(rows)
    for i, (u, candidates) in enumerate(unions.items(), 1):
        group = f'U{i}'
        reuse = list(u) == a
        arms = ['BASE', *candidates]
        if reuse:
            new = [dict(r, group=group) for r in rows if r['group'] == 'A' and r['arm'] in arms]
        else:
            new = batch(group, arms, list(u), args, manifest)
            executed += len(new)
        rows += new
        union_groups[group] = dict(codes=list(u), candidates=candidates, reused_A=reuse)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)
    unchanged = fingerprint({ROOT / p for p in manifest['inputs']}) == manifest['inputs']
    assert unchanged
    save('verification.json', dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'), inputs_unchanged=unchanged, baseline_values_checked=checks,
         baseline_paths=28, baseline_windows_identical=True, executed_paths=executed, summary_rows=len(rows),
         union_groups=union_groups))
    print(f'SCAN COMPLETE {executed} paths / {len(rows)} rows; BASE reproduced against the landed OI-167 scan.', flush=True)


if __name__ == '__main__':
    main()
