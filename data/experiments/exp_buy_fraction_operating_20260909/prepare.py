"""Freeze inputs and the fraction grid; verify production-state equivalence."""
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
PRIOR = EXP.parent / 'exp_buy_line_operating_20260909'
WCEXP = EXP.parent / 'exp_oi168_wc_20260909'
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fingerprint(paths):
    result = {}
    for p in sorted(paths):
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''): h.update(block)
        result[str(p.relative_to(ROOT))] = {'bytes': p.stat().st_size, 'sha256': h.hexdigest()}
    return result


def digest(path, codes=None):
    h = hashlib.sha256(); n = 0
    with path.open(newline='') as f:
        reader = csv.reader(f); header = next(reader); i = header.index('security_code')
        h.update((','.join(header) + '\n').encode())
        for row in reader:
            if codes is None or row[i] in codes:
                h.update((','.join(row) + '\n').encode()); n += 1
    return {'sha256': h.hexdigest(), 'rows': n}


def main():
    args = shlex.split(sw.BASE)
    assert args[args.index('--width')+1] == '-0.0454' and args[args.index('--swap-margin')+1] == '0.15'
    states = WCEXP / 'val/WCOP/states_base.csv'; hold = WCEXP / 'val/WCOP/states_hold.csv'
    state_args = f'--daily-states {states.relative_to(ROOT)} --hold-states {hold.relative_to(ROOT)}'
    grid = [{'arm': 'BASE', 'kind': 'fixed', 'value': 1.0454},
            {'arm': 'FIX110FR09', 'kind': 'fixed_control', 'value': 1.10}]
    grid += [{'arm': f'PCT{i}OP09', 'kind': 'fraction', 'value': i / 100} for i in range(16, 25)]
    save('grid.json', grid)
    configs = []
    for r in grid:
        extra = f"--buy-top-pct {r['value']:.2f}" if r['kind'] == 'fraction' else f"--width {1-r['value']:.4f}"
        configs.append(f"{r['arm']}|{state_args} {extra}")
    (EXP / 'configs.txt').write_text('\n'.join(configs) + '\n')
    with (ROOT / 'data/backtest/scan_summaries.csv').open() as f:
        tags = {sw.summary_tag(arm, start, suffix) for arm in ('BASE', 'BL11000OP09')
                for start in sw.DEFAULT_STARTS for suffix in ('', 'fixed')}
        registered = [r for r in csv.DictReader(f) if r['扫描标签'] in tags]
    assert len(registered) == 56
    with (EXP / 'baseline_before.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(registered[0]), lineterminator='\n'); w.writeheader(); w.writerows(registered)
    prior = json.loads((PRIOR / 'manifest.json').read_text())
    sources = {ROOT / name for name in prior['inputs'] if not name.startswith('data/experiments/exp_buy_line_operating_20260909/')}
    sources.update((ROOT / 'scripts').glob('*.py'))
    sources |= {EXP / name for name in ('prepare.py', 'run.py', 'scan.py', 'audit_fraction.py', 'preregister.md',
                                      'configs.txt', 'grid.json', 'baseline_before.csv')}
    before = fingerprint(sources)
    for name, item in prior['inputs'].items():
        if name in before and name.startswith(('data/raw/', 'data/reference/', 'data/processed/', 'data/interim/',
                                               'data/experiments/exp_oi168_wc_20260909/')):
            assert before[name] == item, f'Data changed since prior scan: {name}'
    # End dates are checked again against the actual panel price files.
    import backtest_valuation_strategy as bt
    panel = ROOT / args[args.index('--universe-file')+1]
    universe = bt.load_universe(panel); codes = {c for _, members in universe for c in members}
    ends = {}
    for code in codes:
        path = ROOT / f'data/raw/ohlcv/{code}.csv'
        with path.open('rb') as f:
            header = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0, 2); f.seek(max(0, f.tell()-4096)); row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        end = row[header.index('date')]; ends[end] = ends.get(end, 0) + 1
    assert ends == prior['price_ends']
    save('manifest.json', {'started_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
        'job_id': os.environ.get('SLURM_JOB_ID'), 'base': sw.BASE, 'starts': sw.DEFAULT_STARTS,
        'metric': sw.METRIC_VERSION, 'inputs': before, 'panel_codes': len(codes),
        'price_ends': ends, 'candidate_count': 9, 'known_nonbase_controls': 1})
    all_codes = set((WCEXP / 'codes.txt').read_text().split())
    eq = []
    for subset, option in ((states, '--daily-states'), (hold, '--hold-states')):
        a = digest(subset); b = digest(ROOT / args[args.index(option)+1], all_codes)
        assert a == b
        eq.append({'side': subset.name, 'subset': a, 'production': b, 'equal': True})
    save('production_equivalence.json', eq)
    from audit_fraction import audit
    audit({'full': []})
    unchanged = fingerprint(sources) == before
    save('prepare_verification.json', {'inputs_unchanged': unchanged, 'equivalence': eq,
                                      'configurations': len(grid), 'candidate_count': 9})
    assert unchanged
    print('PREPARE COMPLETE: 11 configurations, 9 new fractions; frozen data verified.', flush=True)


if __name__ == '__main__': main()
