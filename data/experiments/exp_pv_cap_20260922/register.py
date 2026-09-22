"""Append candidate evidence to the standard ledger without replacing BASE."""
import csv
import json
import os
import re
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import clean_derived_artifacts as ledger
import sweep_backtest_configs as sw


def main():
    v = json.loads((EXP / 'verification.json').read_text())
    assert v['complete_pairing'] and v['zero_negative_cash']
    winners = json.loads((EXP / 'winners.json').read_text())
    with ledger.MERGED.open() as f:
        before = list(csv.DictReader(f))
    with (EXP / 'summary_rows.csv').open() as f:
        rows = [r for r in csv.DictReader(f) if r['arm'] != 'BASE']
    paths = []
    for r in rows:
        tag = sw.summary_tag('PVC' + r['arm'][2:], r['start'],
                             ','.join(winners['A']) if r['group'] == 'A' else '')
        clean = {k: value for k, value in r.items() if k not in ('group', 'arm', 'start', 'tag')}
        assert clean['策略'].endswith('_' + r['tag'])
        clean['策略'] = clean['策略'][:-len(r['tag'])] + tag
        p = EXP / 'cache' / ('summary_' + tag + '.csv')
        with p.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(clean)); w.writeheader(); w.writerow(clean)
        paths.append(p)
    names = {p.name for p in paths}
    with os.scandir(EXP / 'cache') as it:
        entries = [entry for entry in it if entry.name in names]
    ledger.write_ledger(entries)
    with ledger.MERGED.open() as f:
        after = list(csv.DictReader(f))
    key = lambda r: (r['扫描标签'], r['策略'], r['计量版本'])
    lookup = {key(r): r for r in after}
    assert all(lookup[key(r)] == r for r in before)
    index = ledger.build_arms_index(apply=False)
    family = [r['臂名'] for r in index if re.fullmatch(r'PVC\d+', r['臂名'])]
    broad = [r['臂名'] for r in index if 'CAP' in r['臂名'].upper() or r['臂名'] in family]
    out = dict(registered_rows=len(rows), added_rows=len(after) - len(before),
               existing_rows_unchanged=True, family='P/V条件化单票上限（PVC前缀）',
               family_arms=family, family_count=len(family),
               broader_cap_name_inventory=broad, broader_count=len(broad),
               broader_inventory_note='按CAP臂名检索的相关历史研究索引；包含交叉参数，不等于独立试验。')
    (EXP / 'registration.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print('REGISTERED', len(rows), 'candidate rows; family arms', family)


if __name__ == '__main__':
    main()
