#!/usr/bin/env python3
"""Independent cash-start BASE paths and calendar-month forward returns.

Run through scripts/slurm/startup_horizon_returns_20260915.sbatch. The capture
mode only records the native engine's NAV; it does not replace trading logic.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import json
import math
import os
import shlex
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt
import sweep_backtest_configs as sw

HORIZONS = (1, 3, 6, 12, 36)
NAV_FIELDS = ('date', 'net_equity', 'cash', 'positions', 'debt',
              'margin_ratio', 'top1_weight', 'top3_weight')
PRIOR = ROOT / 'data/experiments/exp_oi180_189_20260914'


def add_months(start: str, months: int) -> str:
    d = date.fromisoformat(start)
    if d.day != 1:
        raise ValueError('Calendar-month starts must be the first of a month')
    y, m = divmod(d.year * 12 + d.month - 1 + months, 12)
    return date(y, m + 1, 1).isoformat()


def period_end(start: str, months: int) -> str:
    return (date.fromisoformat(add_months(start, months)) - timedelta(days=1)).isoformat()


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


def save(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def capture(out: Path, engine_args: list[str]) -> None:
    tag = engine_args[engine_args.index('--label-suffix') + 1].lstrip('_')
    original = bt.summarize

    def summarize(name, result, capital, benchmark, risk_free):
        # The first T+1 waiting day has six fields in the native engine.
        with (out / 'nav' / f'{tag}.csv').open('w', newline='') as f:
            w = csv.writer(f)
            w.writerow(NAV_FIELDS)
            w.writerows(tuple(row) + (0.,) * (len(NAV_FIELDS) - len(row))
                        for row in result['equity'])
        return original(name, result, capital, benchmark, risk_free)

    bt.summarize = summarize
    sys.argv = [str(ROOT / 'scripts/backtest_valuation_strategy.py'), *engine_args]
    raise SystemExit(bt.main())


def prepare(out: Path, first: str, cutoff: str, step: int) -> dict:
    prior = json.loads((PRIOR / 'manifest.json').read_text())
    flags = shlex.split(sw.BASE)
    panel = ROOT / flags[flags.index('--universe-file') + 1]
    with panel.open() as f:
        codes = {r['security_code'] for r in csv.DictReader(f)}
    # Reuse only when BOTH full production files and their previously checked
    # panel subsets are byte-identical to the recorded equivalence audit.
    sources = {panel, Path(__file__), ROOT / 'scripts/backtest_valuation_strategy.py',
               ROOT / 'scripts/sweep_backtest_configs.py', ROOT / 'scripts/lot_cooldown.py',
               ROOT / 'scripts/equity_bond_constraint.py', ROOT / 'scripts/swap_chop_guard.py',
               bt.ACTIONS, bt.DELISTED_ROSTER, bt.RATES, bt.NAMES_PATH, bt.BENCHMARK,
               ROOT / flags[flags.index('--equity-bond-data') + 1], out / 'preregister.md'}
    sources.update(ROOT / flags[flags.index(flag) + 1]
                   for flag in ('--daily-states', '--hold-states'))
    sources.update(ROOT / p for p in prior['state_args'][1::2])
    sources.update(bt.OHLCV_DIR / f'{c}.csv' for c in codes)
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)}
    check_names = [str(panel.relative_to(ROOT)), *prior['state_args'][1::2],
                   *(flags[flags.index(f) + 1] for f in ('--daily-states', '--hold-states'))]
    for name in check_names:
        if inputs[name] != prior['inputs'][name]:
            raise ValueError(f'Input changed; refresh panel equivalence before running: {name}')
    ends = {}
    for code in sorted(codes):
        p = bt.OHLCV_DIR / f'{code}.csv'
        with p.open('rb') as f:
            header = f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            row = next(csv.reader(f.read().decode().splitlines()[-1:]))
        ends[code] = row[header.index('date')]
    delisted = bt.load_delisted()
    short = {c: d for c, d in ends.items() if d < cutoff and delisted.get(c, '9999-12-31') > cutoff}
    if short:
        raise ValueError(f'Non-delisted prices end before cutoff: {short}')
    with bt.BENCHMARK.open() as f:
        calendar = sorted(r['date'] for r in csv.DictReader(f))
    if calendar[-1] < cutoff:
        raise ValueError('Benchmark trading calendar ends before cutoff')
    starts = []
    s = first
    while s <= cutoff:
        starts.append(s)
        s = add_months(s, step)
    manifest = dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    job_id=os.environ.get('SLURM_JOB_ID'), workflow='v4.188',
                    base=sw.BASE, capital=float(flags[flags.index('--capital') + 1]),
                    metric=sw.METRIC_VERSION, horizons_months=HORIZONS,
                    starts=starts, first=first, cutoff=cutoff, step_months=step,
                    inputs=inputs, price_ends=ends,
                    price_end_counts=dict(collections.Counter(ends.values())),
                    state_args=prior['state_args'],
                    equivalence_source=str((PRIOR / 'manifest.json').relative_to(ROOT)),
                    production_equivalence=prior['production_equivalence'],
                    calendar=calendar)
    save(out / 'manifest.json', manifest)
    return manifest


def run_one(out: Path, manifest: dict, start: str, until: str, tag: str) -> dict:
    command = [sys.executable, str(Path(__file__).resolve()), 'capture', '--out', str(out), '--',
               *shlex.split(manifest['base']), *manifest['state_args'],
               '--since', start, '--until', until, '--slippage-bp', '0',
               '--label-suffix', '_' + tag, '--out-dir', str(out / 'cache')]
    before = time.monotonic()
    with (out / 'errors' / f'{tag}.txt').open('w') as f:
        subprocess.run(command, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
    with (out / 'cache' / f'summary_{tag}.csv').open() as f:
        row = next(csv.DictReader(f))
    if row['负现金日数'] != '0' or row['计量版本'] != manifest['metric']:
        raise ValueError(f'Cash/metric check failed: {tag}')
    return dict(start=start, tag=tag, elapsed_seconds=time.monotonic() - before, **row)


def read_nav(path: Path) -> list[dict]:
    with path.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in NAV_FIELDS[1:]:
            r[k] = float(r[k])
    return rows


def measure(curve: list[dict], start: str, months: int, cutoff: str,
            capital: float, calendar: list[str]) -> dict:
    end = period_end(start, months)
    # Incomplete calendar horizons stay missing even if a partial return exists.
    complete = end <= cutoff
    row = dict(start=start, months=months, scheduled_end=end,
               status='complete' if complete else 'insufficient_followup',
               first_signal_date=curve[0]['date'], first_trade_date='', end_date='',
               trading_days='', end_equity='', cumulative_return='', max_drawdown='')
    if not complete:
        return row
    expected = [d for d in calendar if start <= d <= end]
    dates = [r['date'] for r in curve]
    k = bisect.bisect_right(dates, end)
    sub = curve[:k]
    if [r['date'] for r in sub] != expected:
        raise ValueError(f'Missing/extra NAV days: {start}/{months}')
    if sub[0]['net_equity'] != capital or sub[0]['positions'] != 0 or sub[0]['debt'] != 0:
        raise ValueError(f'Path does not start in cash: {start}')
    peak, dd = capital, 0.
    for r in sub:
        value = r['net_equity']
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Non-finite or non-positive NAV')
        peak = max(peak, value)
        dd = max(dd, 1 - value / peak)
    row.update(first_trade_date=next((r['date'] for r in sub if r['positions'] > 0), ''),
               end_date=sub[-1]['date'], trading_days=len(sub),
               end_equity=sub[-1]['net_equity'],
               cumulative_return=sub[-1]['net_equity'] / capital - 1, max_drawdown=dd)
    return row


def quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def aggregate(rows: list[dict], group: str) -> list[dict]:
    result = []
    for months in HORIZONS:
        selected = [r for r in rows if r['months'] == months and r['status'] == 'complete']
        vals = [r['cumulative_return'] for r in selected]
        worst = min(selected, key=lambda r: r['cumulative_return'])
        best = max(selected, key=lambda r: r['cumulative_return'])
        result.append(dict(group=group, months=months, count=len(vals),
                           mean=statistics.mean(vals), median=statistics.median(vals),
                           p10=quantile(vals, .1), p25=quantile(vals, .25), p75=quantile(vals, .75),
                           positive_count=sum(v > 0 for v in vals),
                           zero_count=sum(v == 0 for v in vals),
                           positive_share=sum(v > 0 for v in vals) / len(vals),
                           worst=worst['cumulative_return'], worst_start=worst['start'],
                           best=best['cumulative_return'], best_start=best['start']))
    return result


def analyze(out: Path, manifest: dict) -> None:
    rows = []
    for start in manifest['starts']:
        curve = read_nav(out / 'nav' / f'{start}.csv')
        rows.extend(measure(curve, start, m, manifest['cutoff'], manifest['capital'],
                            manifest['calendar']) for m in HORIZONS)
    write_csv(out / 'returns_long.csv', rows)
    wide = []
    for start in manifest['starts']:
        own = [r for r in rows if r['start'] == start]
        wide.append(dict(start=start, first_signal_date=own[0]['first_signal_date'],
                         **{f'return_{r["months"]}m': r['cumulative_return'] for r in own}))
    write_csv(out / 'returns_by_start.csv', wide)
    common = {r['start'] for r in rows if r['months'] == 36 and r['status'] == 'complete'}
    summary = aggregate(rows, 'all_available') + aggregate(
        [r for r in rows if r['start'] in common], 'same_starts_with_36m')
    write_csv(out / 'horizon_summary.csv', summary)
    # Deterministic non-overlap diagnostic: starts anchored at the FIRST month,
    # spaced by each horizon, never selected using returns.
    blocks = [r for r in rows if r['status'] == 'complete' and
              ((date.fromisoformat(r['start']).year - date.fromisoformat(manifest['first']).year) * 12
               + date.fromisoformat(r['start']).month - date.fromisoformat(manifest['first']).month)
              % r['months'] == 0]
    write_csv(out / 'nonoverlapping_windows.csv', blocks)
    write_csv(out / 'nonoverlapping_summary.csv', aggregate(blocks, 'nonoverlapping'))
    counts = {str(m): dict(collections.Counter(r['status'] for r in rows if r['months'] == m))
              for m in HORIZONS}
    save(out / 'coverage.json', counts)
    print(json.dumps(summary[:5], ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=('run', 'analyze', 'capture'))
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--first', default='2009-11-01')
    ap.add_argument('--cutoff', default='2026-08-07')
    ap.add_argument('--step-months', type=int, choices=(1, 3, 12), default=1)
    ap.add_argument('--workers', type=int, default=24)
    argv = sys.argv[1:]
    split = argv.index('--') if '--' in argv else len(argv)
    args = ap.parse_args(argv[:split])
    out = args.out.resolve()
    if args.mode == 'capture':
        capture(out, argv[split + 1:])
        return
    if args.mode == 'analyze':
        analyze(out, json.loads((out / 'manifest.json').read_text()))
        return
    if not 1 <= args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', '0')):
        raise ValueError('Run in SLURM with workers within allocation')
    for sub in ('cache', 'nav', 'errors'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    manifest = prepare(out, args.first, args.cutoff, args.step_months)
    print(f'Inputs verified; {len(manifest["starts"])} independent starts', flush=True)
    # Reproduce the registered long anchor before consuming new readouts.
    anchor = run_one(out, manifest, sw.EX5_ANCHOR_START, '2026-08-28', 'verify_anchor')
    with (PRIOR / 'summary_rows.csv').open() as f:
        old = next(r for r in csv.DictReader(f) if r['arm'] == 'SIGNAL'
                   and r['group'] == 'full' and r['bp'] == '0' and r['start'] == sw.EX5_ANCHOR_START)
    diffs = {k: [old[k], anchor[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if old[k] != anchor[k]}
    save(out / 'baseline_reproduction.json', dict(fields=len(sw.FIELDS) + 1,
                                                  differences=diffs, elapsed_seconds=anchor['elapsed_seconds']))
    if diffs:
        raise ValueError(f'Registered baseline changed: {diffs}')
    print(f'Baseline reproduced in {anchor["elapsed_seconds"]:.1f}s', flush=True)
    summaries = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(run_one, out, manifest, s,
                            min(period_end(s, 36), args.cutoff), s): s for s in manifest['starts']}
        for future in as_completed(jobs):
            summaries.append(future.result())
            if len(summaries) % 12 == 0 or len(summaries) == len(jobs):
                print(f'Completed {len(summaries)}/{len(jobs)}', flush=True)
    write_csv(out / 'path_summaries.csv', sorted(summaries, key=lambda r: r['start']))
    anchor_curve = read_nav(out / 'nav' / 'verify_anchor.csv')
    short_curve = read_nav(out / 'nav' / f'{sw.EX5_ANCHOR_START}.csv')
    if short_curve != anchor_curve[:len(short_curve)]:
        raise ValueError('Short independent path differs from long-anchor prefix')
    analyze(out, manifest)
    changed = [p for p, meta in manifest['inputs'].items() if digest(ROOT / p) != meta]
    if changed:
        raise ValueError(f'Inputs changed during execution: {changed}')
    save(out / 'completed.json', dict(job_id=os.environ['SLURM_JOB_ID'],
                                      paths=len(summaries), baseline_fields=len(sw.FIELDS) + 1,
                                      prefix_rows_verified=len(short_curve), unchanged_inputs=True,
                                      completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()))


if __name__ == '__main__':
    main()
