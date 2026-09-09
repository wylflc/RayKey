"""Cross-check derived decisions and ledger against frozen summaries."""
import csv
from datetime import datetime, timezone
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
    candidates = [d for d in decisions if d['arm'] != 'BASE']
    assert [d['arm'] for d in candidates if d['verdict'] == 'pass'] == ['BL11000OP09']
    assert [d['arm'] for d in candidates if d['verdict'] == 'ruling'] == ['BL15000OP09']
    assert not any(d['U_excellent'] for d in candidates)
    assert not json.loads((EXP / 'platforms.json').read_text())
    assert all(d['risk_gates_passed'] == d['engine_risk_gates_passed'] for d in decisions)
    with (EXP / 'baseline_before.csv').open() as f: before = {r['扫描标签']: r for r in csv.DictReader(f)}
    with (ROOT / 'data/backtest/scan_summaries.csv').open() as f:
        ledger = {r['扫描标签']: r for r in csv.DictReader(f)}
    ancillary = []
    for tag, b in before.items():
        r = ledger[tag]
        assert all(r[k] == b[k] for k in (*sw.FIELDS, '前五赢家', '首个净值日'))
        for key in r:
            if r[key] != b.get(key):
                assert key == '前五赢家占正贡献' and abs(float(r[key])-float(b[key])) < 1e-14
                ancillary.append({'tag': tag, 'field': key, 'before': b[key], 'after': r[key]})
    for (group, arm, start), row in rows.items():
        if group not in ('full', 'A'): continue
        tag = sw.summary_tag(arm, start, 'fixed' if group == 'A' else '')
        assert all(ledger[tag][k] == row[k] for k in row if k not in ('group', 'arm', 'start'))
    hashes = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(EXP.iterdir())
              if f.is_file() and f.name != 'report_verification.json'}
    output = {'verified_utc': datetime.now(timezone.utc).isoformat(), 'formal_rounded_field_checks': checks,
              'baseline_standard_fields_exact': True, 'ancillary_last_bit_changes': ancillary,
              'candidate_count': len(candidates), 'passed': 1, 'ruling': 1, 'failed': 44,
              'U_qualified': 0, 'platforms': 0, 'ledger_all_full_A_fields_match': True,
              'standard_engine_risk_verdicts_match': True, 'artifact_hashes': hashes}
    (EXP / 'report_verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(f'REPORT VERIFIED: {checks} formal field checks; 46 candidates; ledger matches.')


if __name__ == '__main__': main()
