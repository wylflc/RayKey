#!/usr/bin/env python3
"""核验九家补接的时间边界、其余历史不变及修复前后完整回测。"""
import csv
import hashlib
import io
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from sweep_backtest_configs import DEFAULT_STARTS, FIELDS, load_scan


def main():
    exp = ROOT / 'data/experiments/exp_oi165_panel'
    evidence = json.loads((exp/'entry_evidence.json').read_text())
    entries = {r['security_code']: r for r in evidence['entries']}
    checks = {}
    for side in ('a', 'b'):
        name = f'data/processed/pit_attention/panel_moat_bank_v6{side}.csv'
        old_data = subprocess.check_output(['git', 'show', f"{evidence['base_commit']}:{name}"], cwd=ROOT)
        old = list(csv.DictReader(io.StringIO(old_data.decode())))
        new = list(csv.DictReader((ROOT/name).open()))
        def unchanged(rows):
            return Counter(tuple(r.items()) for r in rows if r['security_code'] not in entries)
        checks[f'v6{side}_other_codes_exact'] = unchanged(old) == unchanged(new)
        for code, entry in entries.items():
            day = entry['as_of']
            def preceding(rows):
                return Counter(tuple({**r, 'effective_to': min(r['effective_to'] or '9999-12-31', day)}.items())
                               for r in rows if r['security_code'] == code and r['effective_from'] < day)
            checks[f'v6{side}_{code}_prior_history_exact'] = preceding(old) == preceding(new)
            intervals = [r for r in new if r['security_code'] == code and r['effective_from'] == day
                         and not r['effective_to']]
            checks[f'v6{side}_{code}_one_new_open_interval'] = len(intervals) == 1
        if side == 'b':
            active = {r['security_code'] for r in new if r['effective_from'] <= '2026-09-07' <= (r['effective_to'] or '9999-12-31')}
            core = {r['security_code'] for r in csv.DictReader((ROOT/'data/processed/a_share_core_valuation_pool.csv').open())
                    if r['market_type'] == 'A_SHARE'}
            checks['current_pool_complete'] = core <= active
            counts = {'current_pool': len(core), 'current_panel': len(active), 'missing': sorted(core-active)}
    groups, _order, failed, ex5, version, fields = load_scan(exp/'sweep_guard.txt')
    checks['no_failed_paths'] = not any(failed.values())
    checks['metric_m2'] = version == 'm2'
    for label, arms in groups.items():
        before, after = arms['BASE'], arms['OI165']
        checks[f'{label or "full"}_14_paired_starts'] = set(before) == set(after) == set(DEFAULT_STARTS)
        checks[f'{label or "full"}_all_reported_fields_exact'] = before == after
    assert set(groups) == {'', 'EX5:'}
    assert all(checks.values()), checks
    report = {'checks': checks, 'counts': counts, 'paths': 56, 'fields_per_path': len(fields),
              'comparison': 'Each of 28 full/A paired paths is identical on every reported numeric field',
              'exclusion': ex5, 'slurm_job_id': '26454938', 'elapsed': '00:02:59',
              'entries': [{'code': c, 'name': r['security_name'], 'effective_from': r['as_of'],
                           'decision_id': r['decision_id']} for c, r in sorted(entries.items())],
              'source_commit': evidence['base_commit']}
    (exp/'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': len(checks), 'counts': counts, 'paths':56, 'fields':len(fields)},ensure_ascii=False))


if __name__ == '__main__':
    main()
