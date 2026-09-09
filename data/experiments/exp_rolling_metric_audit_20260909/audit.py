"""Diagnose aggregation without changing trading rules or adoption criteria."""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import statistics as st
import subprocess
import sys
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
OLD = ROOT / 'data/experiments/exp_equity_bond_20260909/high_base'
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt


def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_csv(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def rows_by_key():
    return {(r['group'], r['arm'], r['start']): r
            for r in read_csv(OLD / 'summary_rows.csv') if r['group'] in ('full', 'A')}


def prepare():
    old = json.loads((OLD / 'manifest.json').read_text())
    # Record only fingerprints here; validate the frozen input set on the compute node.
    paths = [EXP / 'audit.py', EXP / 'preregister.md', OLD / 'manifest.json',
             OLD / 'summary_rows.csv', OLD / 'configs.txt']
    save('manifest.json', {'created_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         'source_manifest': str((OLD / 'manifest.json').relative_to(ROOT)),
         'base': old['base'], 'starts': old['starts'], 'metric': old['metric'],
         'audit_inputs': {str(p.relative_to(ROOT)): sha(p) for p in paths},
         'purpose': 'aggregation diagnosis only; no strategy or gate change'})


def worker(group, start):
    old = json.loads((OLD / 'manifest.json').read_text())
    extra = dict(line.split('|', 1) for line in (OLD / 'configs.txt').read_text().splitlines())['BASE']
    tag = f'BASE{start.replace("-", "")}' + ('ex5' if group == 'A' else '')
    expected = rows_by_key()[group, 'BASE', start]
    output = EXP / 'curves' / f'{group}_{start}.json'
    output.parent.mkdir(exist_ok=True)
    original = bt.summarize

    def capture(name, result, capital, benchmark, risk_free):
        summary = original(name, result, capital, benchmark, risk_free)
        roundoff = {}
        for key, value in summary.items():
            if key != '策略' and str(value) != expected[key]:
                assert isinstance(value, (float, int)) and math.isclose(
                    value, float(expected[key]), rel_tol=1e-14, abs_tol=1e-14), (
                    group, start, key, value, expected[key])
                roundoff[key] = {'prior': expected[key], 'rerun': value}
        save(str(output.relative_to(EXP)), [[r[0], r[1]] for r in result['equity']])
        save(str(output.with_suffix('.verification.json').relative_to(EXP)),
             {'summary_fields_checked': len(summary) - 1, 'roundoff_only': roundoff})
        return summary

    bt.summarize = capture
    args = shlex.split(old['base']) + shlex.split(extra)
    args += ['--since', start, '--label-suffix', '_' + tag,
             '--out-dir', str(EXP / 'scratch' / tag)]
    if group == 'A':
        codes = rows_by_key()['full', 'BASE', '2011-11-01']['前五赢家'].replace('/', ',')
        args += ['--exclude-codes', codes]
    sys.argv = [sys.argv[0], *args]
    bt.main()
    assert output.exists()


def run(workers):
    manifest = json.loads((EXP / 'manifest.json').read_text())
    frozen = json.loads((OLD / 'manifest.json').read_text())
    for path, digest in manifest['audit_inputs'].items():
        assert sha(ROOT / path) == digest, path
    checked = 0
    # The two production state files are not used: the original experiment's
    # already-verified equivalent WCOP subsets override them in every command.
    unused = {'data/processed/a_share_daily_states_adopted.csv',
              'data/processed/a_share_daily_states_hold.csv'}
    for path, info in frozen['inputs'].items():
        if path not in unused:
            assert sha(ROOT / path) == info['sha256'], path
            checked += 1
    print(f'Frozen inputs verified: {checked}', flush=True)
    (EXP / 'worker_logs').mkdir(exist_ok=True)
    tasks = [(g, s) for g in ('full', 'A') for s in manifest['starts']]

    def launch(task):
        group, start = task
        # Existing curves were emitted only after all summary fields passed.
        # Recheck their rolling statistics again in analyze().
        if (EXP / 'curves' / f'{group}_{start}.json').exists():
            print(f'BASE previously reproduced: {group} {start}', flush=True)
            return
        with (EXP / 'worker_logs' / f'{group}_{start}.txt').open('w') as f:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), 'worker',
                            '--group', group, '--start', start], stdout=f, stderr=subprocess.STDOUT,
                           cwd=ROOT, check=True)
        print(f'BASE reproduced: {group} {start}', flush=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(launch, tasks))
    save('rerun_verification.json', {'job_id': os.environ.get('SLURM_JOB_ID'),
         'baseline_paths': len(tasks), 'all_summary_fields_match_except_label': True,
         'numeric_roundoff_tolerance': 1e-14,
         'frozen_inputs_verified': checked,
         'completed_beijing': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})


def windows(curve):
    ends = bt.month_end_indices(curve)
    by_month = {curve[i][0][:7]: i for i in ends}
    out = []
    for i in ends:
        day = curve[i][0]
        j = by_month.get(f'{int(day[:4]) - 5:04d}-{day[5:7]}')
        if j is None:
            continue
        first, last = curve[j][1], curve[i][1]
        years = (datetime.fromisoformat(day) - datetime.fromisoformat(curve[j][0])).days / 365.25
        peak = 0.0
        mdd = 0.0
        for _, nav in curve[j:i + 1]:
            peak = max(peak, nav)
            mdd = max(mdd, 1 - nav / peak)
        out.append({'from': curve[j][0], 'to': day, 'cagr': (last / first) ** (1 / years) - 1,
                    'mdd': mdd, 'growth': last / first, 'years': years})
    return out


def analyze():
    baseline_check = json.loads((EXP / 'rerun_verification.json').read_text())
    assert baseline_check['baseline_paths'] == 28
    manifest = json.loads((EXP / 'manifest.json').read_text())
    for path, digest in manifest['audit_inputs'].items():
        assert sha(ROOT / path) == digest, path
    starts = manifest['starts']
    summaries = rows_by_key()
    per_start, paired, group_results, fingerprints = [], [], [], {}
    wealth_examples, baseline_fingerprints = [], {}
    for group in ('full', 'A'):
        for start in starts:
            baseline_path = EXP / 'curves' / f'{group}_{start}.json'
            baseline_fingerprints[baseline_path.name] = sha(baseline_path)
            candidate_path = OLD / 'daily/full_A' / ('_EBDS03' + start.replace('-', '') +
                              ('ex5' if group == 'A' else '') + '.csv')
            curves = {'BASE': json.loads(baseline_path.read_text()),
                      'EBDS03': [[r['date'], float(r['equity'])] for r in read_csv(candidate_path)]}
            # The T+1 warm-up branch records the initial cash NAV but emits no
            # equity/bond diagnostic. Restore that known opening observation;
            # never fill later gaps. None of these opening dates is a month end.
            if [r[0] for r in curves['BASE'][1:]] == [r[0] for r in curves['EBDS03']]:
                first_day, initial_cash = curves['BASE'][0]
                assert initial_cash == 3000000 and first_day == summaries[group, 'EBDS03', start]['首个净值日']
                curves['EBDS03'].insert(0, [first_day, initial_cash])
            assert [r[0] for r in curves['BASE']] == [r[0] for r in curves['EBDS03']]
            fingerprints[str(candidate_path.relative_to(ROOT))] = sha(candidate_path)
            ws = {arm: windows(curve) for arm, curve in curves.items()}
            for arm, values in ws.items():
                old = summaries[group, arm, start]
                cagr = sorted(w['cagr'] for w in values)
                checks = {'滚动5年年化中位': st.median(cagr), '滚动5年年化P25': cagr[len(cagr) // 4],
                          '滚动5年年化最差': min(cagr), '滚动5年回撤中位': st.median(w['mdd'] for w in values),
                          '滚动5年窗口数': len(values)}
                for key, value in checks.items():
                    assert math.isclose(value, float(old[key]), rel_tol=1e-12, abs_tol=1e-12), (group, start, arm, key)
            diffs = []
            for b, c in zip(ws['BASE'], ws['EBDS03'], strict=True):
                assert (b['from'], b['to']) == (c['from'], c['to'])
                delta = 100 * (c['cagr'] - b['cagr'])
                diffs.append(delta)
                record = {'group': group, 'start': start, 'window_from': b['from'], 'window_to': b['to'],
                    'BASE_cagr': b['cagr'], 'EBDS03_cagr': c['cagr'], 'delta_pp': delta,
                    'BASE_mdd': b['mdd'], 'EBDS03_mdd': c['mdd'],
                    'relative_growth': c['growth'] / b['growth'],
                    'relative_log_growth_per_year': math.log(c['growth'] / b['growth']) / b['years']}
                assert math.isclose(math.log1p(c['cagr']) - math.log1p(b['cagr']),
                                    record['relative_log_growth_per_year'], abs_tol=1e-12)
                paired.append(record)
                if (group == 'full' and start in ('2009-11-01', '2011-11-01', '2014-11-01')
                        and b['from'] == '2016-07-29' and b['to'] == '2021-07-30'):
                    base_nav, candidate_nav = dict(curves['BASE']), dict(curves['EBDS03'])
                    q0 = candidate_nav[b['from']] / base_nav[b['from']]
                    q1 = candidate_nav[b['to']] / base_nav[b['to']]
                    assert math.isclose(q1 / q0, record['relative_growth'], abs_tol=1e-12)
                    wealth_examples.append({**record, 'relative_wealth_start': q0, 'relative_wealth_end': q1})
            b, c = summaries[group, 'BASE', start], summaries[group, 'EBDS03', start]
            per_start.append({'group': group, 'start': start, 'windows': len(diffs),
                'BASE_roll5_median': float(b['滚动5年年化中位']),
                'EBDS03_roll5_median': float(c['滚动5年年化中位']),
                'current_delta_pp': 100 * (float(c['滚动5年年化中位']) - float(b['滚动5年年化中位'])),
                'matched_window_median_pp': st.median(diffs), 'matched_window_mean_pp': st.mean(diffs),
                'matched_window_win_fraction': sum(d > 0 for d in diffs) / len(diffs),
                'BASE_cagr': float(b['年化']), 'EBDS03_cagr': float(c['年化']),
                'cagr_delta_pp': 100 * (float(c['年化']) - float(b['年化'])),
                'final_wealth_ratio': float(c['期末资产']) / float(b['期末资产'])})
        rows = [r for r in per_start if r['group'] == group]
        calendar = defaultdict(list)
        for r in paired:
            if r['group'] == group:
                calendar[r['window_from'], r['window_to']].append(r['delta_pp'])
        group_results.append({'group': group, 'current_delta_pp': st.median(r['current_delta_pp'] for r in rows),
            'difference_of_level_medians_pp': 100 * (st.median(r['EBDS03_roll5_median'] for r in rows) -
                                                   st.median(r['BASE_roll5_median'] for r in rows)),
            'matched_window_median_then_start_median_pp': st.median(r['matched_window_median_pp'] for r in rows),
            'start_equal_weight_mean_pp': st.mean(r['matched_window_mean_pp'] for r in rows),
            'calendar_equal_weight_mean_pp': st.mean(st.mean(v) for v in calendar.values()),
            'median_within_start_win_fraction': st.median(r['matched_window_win_fraction'] for r in rows),
            'current_positive_starts': sum(r['current_delta_pp'] > 0 for r in rows),
            'matched_median_positive_starts': sum(r['matched_window_median_pp'] > 0 for r in rows),
            'cagr_positive_starts': sum(r['cagr_delta_pp'] > 0 for r in rows),
            'total_paired_windows': sum(r['windows'] for r in rows), 'distinct_calendar_windows': len(calendar),
            'calendar_multiplicity_min': min(map(len, calendar.values())),
            'calendar_multiplicity_max': max(map(len, calendar.values()))})
    write_csv('per_start.csv', per_start)
    write_csv('paired_windows.csv', paired)
    write_csv('aggregation_comparison.csv', group_results)
    write_csv('wealth_examples.csv', wealth_examples)
    toy_base, toy_candidate = [5, 10, 20], [9, 9, 21]
    assert st.median(toy_candidate) - st.median(toy_base) == -1
    assert st.median(c - b for b, c in zip(toy_base, toy_candidate)) == 1
    save('verification.json', {'baseline': baseline_check, 'paths_with_reproduced_window_summaries': 56,
         'matched_windows': len(paired), 'candidate_curve_sha256': fingerprints,
         'baseline_curve_sha256': baseline_fingerprints,
         'paired_window_log_wealth_identities_checked': len(paired),
         'wealth_examples_checked': len(wealth_examples), 'conceptual_median_counterexample_checked': True,
         'candidate_opening_cash_nav_restored': 28,
         'trade_rules_changed': False, 'adoption_gate_changed': False,
         'known_legacy_accounting_defects': ['OI-169', 'OI-170']})
    print(json.dumps(group_results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['prepare', 'run', 'worker', 'analyze'])
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--group', choices=['full', 'A'])
    p.add_argument('--start')
    args = p.parse_args()
    if args.action == 'prepare': prepare()
    elif args.action == 'run':
        assert 1 <= args.workers <= int(os.environ.get('SLURM_CPUS_PER_TASK', '1'))
        run(args.workers)
    elif args.action == 'worker': worker(args.group, args.start)
    else: analyze()
