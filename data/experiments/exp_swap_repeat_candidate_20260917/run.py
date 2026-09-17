"""Use the standard scanner with isolated outputs and a verified panel subset."""
import argparse
import csv
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return dict(bytes=path.stat().st_size, sha256=h.hexdigest())


def prepare():
    prior_path = EXP.parent / 'exp_stop_max_20260916/manifest.json'
    prior = json.loads(prior_path.read_text())
    flags = shlex.split(sw.BASE)
    paths = {ROOT / p for p in prior['inputs'] if p.startswith(('data/raw/', 'data/reference/'))}
    paths |= {ROOT / flags[flags.index(k) + 1] for k in ('--universe-file', '--daily-states', '--hold-states')}
    paths |= {ROOT / p for p in prior['state_args'] if p.endswith('.csv')}
    paths |= set((ROOT / 'scripts').glob('*.py')) | {prior_path, EXP / 'preregister.md', EXP / 'run.py', EXP / 'engine.py', EXP / 'test_repeat.py'}
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}
    for flag in ('--daily-states', '--hold-states'):
        for args in (flags, prior['state_args']):
            name = args[args.index(flag) + 1]
            assert hashes[name] == prior['inputs'][name], ('subset equivalence changed', name)
    panel = flags[flags.index('--universe-file') + 1]
    assert hashes[panel] == prior['inputs'][panel], 'universe changed; must reverify subset'
    ends = {}
    for code in prior['price_ends']:
        path = ROOT / f'data/raw/ohlcv/{code}.csv'
        with path.open('rb') as f:
            header = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        ends[code] = row[header.index('date')]
    save('manifest.json', dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'), base=sw.BASE, starts=sw.DEFAULT_STARTS,
         metric=sw.METRIC_VERSION, inputs=hashes, state_args=prior['state_args'],
         equivalence_evidence=str(prior_path.relative_to(ROOT)),
         production_equivalence=prior['production_equivalence'], price_ends=ends,
         price_end_counts=dict(Counter(ends.values()))))
    extra = shlex.join(prior['state_args']) + ' --equity-bond-log-dir ' + str(EXP / 'daily')
    (EXP / 'configs.txt').write_text('BASE|' + extra + '\nREPEAT|' + extra + ' --repeat-swap-candidate\n')
    print('PREPARED:', dict(Counter(ends.values())), flush=True)


def verify_inputs():
    manifest = json.loads((EXP / 'manifest.json').read_text())
    assert manifest['base'] == sw.BASE and manifest['starts'] == sw.DEFAULT_STARTS
    changed = [p for p, meta in manifest['inputs'].items() if digest(ROOT / p) != meta]
    assert not changed, changed
    return manifest


def summary(path):
    with path.open() as f:
        return next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))


def smoke():
    manifest = verify_inputs()
    started = time.monotonic()
    rows = []
    for arm in ('NATIVE', 'BASE', 'REPEAT'):
        script = ROOT / 'scripts/backtest_valuation_strategy.py' if arm == 'NATIVE' else EXP / 'engine.py'
        command = [sys.executable, str(script), *shlex.split(sw.BASE), *manifest['state_args'],
                   '--since', sw.EX5_ANCHOR_START, '--out-dir', str(EXP / 'smoke'),
                   '--label-suffix', '_SMOKE' + arm]
        if arm == 'REPEAT': command += ['--repeat-swap-candidate']
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
        rows.append(summary(EXP / 'smoke' / f'summary_SMOKE{arm}.csv'))
    keys = (*sw.FIELDS, sw.WIN5_KEY, '期末资产', '买入笔数', '卖出笔数', '前五赢家')
    differences = {k: [rows[0][k], rows[1][k]] for k in keys if rows[0][k] != rows[1][k]}
    assert not differences, differences
    save('smoke.json', dict(elapsed_seconds=time.monotonic() - started,
         job_id=os.environ.get('SLURM_JOB_ID'), native_vs_instrumented_differences=differences,
         fields_checked=len(keys), rows=[{k: r[k] for k in ('期末资产', '年化', '最大回撤', '负现金日数')} for r in rows]))
    assert all(r['负现金日数'] == '0' for r in rows)
    print('SMOKE COMPLETE; native baseline reproduced', flush=True)


def run_one(job):
    label, extra, since, exclude = job
    tag = sw.summary_tag(label, since, exclude)
    out_label = sw.EX5_PREFIX + label if exclude else label
    command = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE),
               '--since', since, '--label-suffix', '_' + tag, '--out-dir', str(sw.OUT_DIR),
               *shlex.split(extra)]
    if exclude: command += ['--exclude-codes', exclude]
    if not exclude and since in ('2009-11-01', '2011-11-01'):
        command += ['--trade-log', str(EXP / 'traces' / f'ledger_{tag}.csv'),
                    '--candidate-log', str(EXP / 'traces' / f'candidates_{tag}.csv')]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=f)
    sw.RUN_DIR.mkdir(parents=True, exist_ok=True)
    (sw.RUN_DIR / f'summary_{tag}.csv').write_bytes((sw.OUT_DIR / f'summary_{tag}.csv').read_bytes())
    row = summary(sw.OUT_DIR / f'summary_{tag}.csv')
    assert row['计量版本'] == sw.METRIC_VERSION and row['负现金日数'] == '0'
    line = '|'.join([out_label, since] + [f'{sw._field_value(row,k):.6f}' for k in sw.FIELDS])
    return line + '\n' + f'{sw.WIN5_HEADER}{out_label}|{since}|{row[sw.WIN5_KEY]}'


def scan(workers):
    verify_inputs()
    configs = dict(line.split('|', 1) for line in (EXP / 'configs.txt').read_text().splitlines())
    assert shlex.split(configs['REPEAT']) == shlex.split(configs['BASE']) + ['--repeat-swap-candidate']
    assert workers <= int(os.environ['SLURM_CPUS_PER_TASK'])
    sw.OUT_DIR = EXP / 'cache'
    sw.RUN_DIR = sw.OUT_DIR / 'run'
    sw.OUT_DIR.mkdir(exist_ok=True)
    for name in ('errors', 'traces', 'daily'):
        (EXP / name).mkdir(exist_ok=True)
    sw.run_one = run_one
    sys.argv = ['sweep_backtest_configs.py', str(EXP / 'configs.txt'), '--out',
                str(EXP / 'sweep_full_A.txt'), '--workers', str(workers), '--title', '同一候选连续触发换仓']
    with (EXP / 'report_full_A.txt').open('w') as f:
        from contextlib import redirect_stdout
        with redirect_stdout(f):
            sw.main()
    groups, _, failed, _, _, _ = sw.load_scan(EXP / 'sweep_full_A.txt')
    assert not any(failed.values()), failed
    winners = {}
    for arm in ('BASE', 'REPEAT'):
        winners[arm] = sorted(summary(sw.OUT_DIR / f'summary_{sw.summary_tag(arm, sw.EX5_ANCHOR_START)}.csv')['前五赢家'].split('/'))
        assert len(winners[arm]) == 5
    a = winners['BASE']
    u = sorted(set(a) | set(winners['REPEAT']))
    save('winner_sets.json', dict(A=a, U=u, by_arm=winners, U_reused_A=(u == a)))
    # Preserve A summaries before the fixed-U pass reuses the standard tags.
    for path in sw.OUT_DIR.glob('summary_*.csv'):
        dest = sw.OUT_DIR / 'full_A' / path.name
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(path.read_bytes())
    for directory in ('nav', 'stats', 'swaps', 'daily'):
        for path in (EXP / directory).glob('*'):
            if path.is_file():
                dest = EXP / directory / 'full_A' / path.name
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(path.read_bytes())
    if u != a:
        sys.argv = ['sweep_backtest_configs.py', str(EXP / 'configs.txt'), '--out',
                    str(EXP / 'sweep_U.txt'), '--workers', str(workers), '--exclude-codes', ','.join(u)]
        with (EXP / 'report_U.txt').open('w') as f:
            with redirect_stdout(f):
                sw.main()
        _, _, failed, _, _, _ = sw.load_scan(EXP / 'sweep_U.txt')
        assert not any(failed.values()), failed
    verify_inputs()
    save('completed.json', dict(job_id=os.environ.get('SLURM_JOB_ID'), inputs_unchanged=True,
         paths=56 if u == a else 84, U_reused_A=(u == a)))
    print('SCAN COMPLETE', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('prepare', 'smoke', 'scan'))
    parser.add_argument('--workers', type=int, default=24)
    args = parser.parse_args()
    if args.stage == 'prepare':
        prepare()
    elif args.stage == 'smoke':
        smoke()
    else:
        scan(args.workers)
