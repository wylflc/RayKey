"""Check scan fields, both fixed controls, ledger rows, and every daily fraction count."""
import csv
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw


def main():
    with (EXP / 'summary_rows.csv').open() as f:
        rows = {(r['group'], r['arm'], r['start']): r for r in csv.DictReader(f)}
    v = json.loads((EXP / 'verification.json').read_text())
    assert v['inputs_unchanged'] and len(v['baseline_checks']) == 56
    checks = 0
    for cache in ['full_A', *[g for g, x in v['union_groups'].items() if not x['reused_A']]]:
        groups, _, failed, _, version, fields = sw.load_scan(EXP / f'sweep_{cache}.txt')
        assert version == sw.METRIC_VERSION and fields == sw.FIELDS and not any(failed.values())
        for prefix, arms in groups.items():
            group = ('A' if prefix else 'full') if cache == 'full_A' else cache
            for arm, starts in arms.items():
                for start, numbers in starts.items():
                    raw = rows[group, arm, start]
                    for key in sw.FIELDS:
                        a, b = numbers[key], sw._field_value(raw, key)
                        assert (math.isnan(a) and math.isnan(b)) or a == b or abs(a-b) <= 5.01e-7, (group, arm, start, key, a, b)
                        checks += 1
    assert checks == v['executed_paths'] * len(sw.FIELDS)
    for group, info in v['union_groups'].items():
        assert all((group, arm, start) in rows for arm in ['BASE', *info['candidates']] for start in sw.DEFAULT_STARTS)
    decisions = json.loads((EXP / 'decisions.json').read_text())
    candidates = [d for d in decisions if d['kind'] == 'fraction']
    assert len(candidates) == 9 and all(d['verdict'] == 'fail' for d in candidates)
    assert not any(d['U_excellent'] for d in candidates)
    assert not json.loads((EXP / 'platforms.json').read_text())
    with (EXP / 'baseline_before.csv').open() as f: previous = {r['扫描标签']: r for r in csv.DictReader(f)}
    for group in ('full', 'A'):
        for arm, old in (('BASE', 'BASE'), ('FIX110FR09', 'BL11000OP09')):
            for start in sw.DEFAULT_STARTS:
                b = previous[sw.summary_tag(old, start, 'fixed' if group == 'A' else '')]
                r = rows[group, arm, start]
                assert all(r[k] == b[k] for k in (*sw.FIELDS, '前五赢家', '首个净值日'))
    with (ROOT / 'data/backtest/scan_summaries.csv').open() as f:
        ledger = {r['扫描标签']: r for r in csv.DictReader(f)}
    for (group, arm, start), row in rows.items():
        if group not in ('full', 'A'): continue
        tag = sw.summary_tag(arm, start, 'fixed' if group == 'A' else '')
        assert all(ledger[tag][k] == row[k] for k in row if k not in ('group', 'arm', 'start'))
    counts = 0; compressed = []
    for file in sorted(EXP.glob('daily_selection_*.csv.gz')):
        h = hashlib.sha256()
        with gzip.open(file, 'rb') as f:
            for block in iter(lambda: f.read(1 << 20), b''): h.update(block)
        local = file.with_suffix('')
        assert h.hexdigest() == hashlib.sha256(local.read_bytes()).hexdigest()
        compressed.append({'file': file.name, 'uncompressed_sha256': h.hexdigest()})
        last_day = None; last_count = 0; last_cutoff = 0.
        with gzip.open(file, 'rt', newline='') as f:
            for row in csv.DictReader(f):
                assert row['signal_day'] < row['execution_day']
                n, selected = int(row['denominator']), int(row['selected'])
                assert 0 <= int(row['potential_new_entry_count']) <= int(row['potential_addon_count']) <= int(row['execution_members_and_price']) <= selected <= n
                if row['signal_day'] != last_day:
                    last_day = row['signal_day']; last_count = 0; last_cutoff = 0.
                if row['kind'] == 'fraction':
                    q = Fraction(row['value'])
                    assert selected == n*q.numerator//q.denominator
                    assert selected >= last_count
                    if row['pv_cutoff']:
                        assert float(row['pv_cutoff']) >= last_cutoff
                        last_cutoff = float(row['pv_cutoff'])
                    last_count = selected
                    assert abs(float(row['share']) - selected/n) < 1e-14 if n else row['share'] == ''
                    counts += 1
    assert len(compressed) == 5 and counts == 5*4088*9
    output = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'formal_rounded_field_checks': checks,
              'fixed_control_paths_exact': 56, 'ledger_all_full_A_fields_match': True,
              'daily_fraction_rows_checked': counts, 'daily_counts_nested_and_floor_exact': True,
              'compressed_evidence': compressed, 'fraction_candidates': 9, 'passed': 0, 'U_qualified': 0,
              'platforms': 0, 'standard_engine_risk_verdict_differences': [d['arm'] for d in decisions if d['risk_gates_passed'] != d['engine_risk_gates_passed']]}
    output['artifact_hashes'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(EXP.iterdir())
                                if f.is_file() and f.name != 'report_verification.json' and not f.name.startswith('daily_selection_')}
    (EXP / 'report_verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(f'REPORT VERIFIED: {checks} standard cells, {counts} daily fraction rows, 56 exact controls.')


if __name__ == '__main__': main()
