"""P 臂两份附注输入（生产表不动）：现行 `fetch_cash_note_items.py`（放宽表头与无序号标题、并入人工核定表）与
`fetch_restricted_cash_items.py` 在缓存原文上 `--parse-only`，写到本目录 `inputs/`。先拷生产表作起点，与生产运行
同一合并语义（清单外的旧行保留）。逐行对照生产表，并核对附注表与发现实验候选表只差人工核定的两家。

    python3 inputs.py
"""
import csv
import json
import shutil
import sys
from collections import Counter

from common import EXP, NOTE_INPUTS, ROOT, digest, save
sys.path.insert(0, str(ROOT / 'scripts'))
import fetch_cash_note_items as cn  # noqa: E402
import fetch_restricted_cash_items as rc  # noqa: E402

DISCOVERY = ROOT / 'data/experiments/exp_oi215_notes_20260925/cash_note_items.csv'   # R1/R2 候选（无人工核定）
MANUAL_CODES = {'600938', '001232'}


def rows(path, key):
    with path.open(newline='', encoding='utf-8') as f:
        return {key(r): r for r in csv.DictReader(f)}


def note_key(r):
    return r['security_code'], int(r['fiscal_year']), r['line']


def restricted_key(r):
    return r['security_code'], int(r['fiscal_year'])


def compare(old, new, fields):
    moves, changed = Counter(), []
    for k in old.keys() | new.keys():
        o, n = old.get(k), new.get(k)
        before, after = (o or {}).get('status', 'absent'), (n or {}).get('status', 'absent')
        moves[f'{before}→{after}'] += 1
        if o is None or n is None or any(o.get(f) != n.get(f) for f in fields):
            changed.append(dict(key=list(k), before=before, after=after, **{f'{f}_before': (o or {}).get(f) for f in fields},
                                **{f'{f}_after': (n or {}).get(f) for f in fields}))
    return dict(moves=dict(moves.most_common()), changed=changed)


def main():
    notes_out, restricted_out = NOTE_INPUTS['P']
    notes_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cn.OUT, notes_out)
    shutil.copyfile(rc.OUT, restricted_out)
    production_notes, production_restricted = cn.OUT, rc.OUT
    cn.OUT, rc.OUT, rc.CASH_NOTES = notes_out, restricted_out, notes_out
    sys.argv = ['fetch_cash_note_items', '--parse-only']
    assert cn.main() == 0
    sys.argv = ['fetch_restricted_cash_items', '--parse-only']
    assert rc.main() == 0
    old_n, new_n = rows(production_notes, note_key), rows(notes_out, note_key)
    old_r, new_r = rows(production_restricted, restricted_key), rows(restricted_out, restricted_key)
    notes_diff = compare(old_n, new_n, ('status', 'cash_like_amount', 'items'))
    restricted_diff = compare(old_r, new_r, ('status', 'counted_yuan', 'generic_yuan', 'source', 'items'))
    # 与发现实验候选表（同一 R1/R2、无人工核定）逐行比：只允许人工核定两家不同
    discovery = rows(DISCOVERY, note_key)
    port = [dict(key=list(k), discovery=(discovery.get(k) or {}).get('status'), now=(new_n.get(k) or {}).get('status'))
            for k in discovery.keys() | new_n.keys() if k[0] not in MANUAL_CODES
            and any((discovery.get(k) or {}).get(f) != (new_n.get(k) or {}).get(f) for f in ('status', 'cash_like_amount', 'items'))]
    verified = lambda d: sum(float(r['statement_amount'] or 0) for r in d.values() if r['status'] in cn.VERIFIED)
    total = sum(float(r['statement_amount'] or 0) for r in new_n.values()) or 1.0
    summary = dict(
        notes=dict(rows=len(new_n), coverage_old=verified(old_n) / total, coverage_new=verified(new_n) / total,
                   cash_old=sum(float(r['cash_like_amount'] or 0) for r in old_n.values()),
                   cash_new=sum(float(r['cash_like_amount'] or 0) for r in new_n.values()),
                   manual_rows=sum(r['status'] == 'manual' for r in new_n.values()),
                   manual_stale=sum(r['status'] == 'manual_stale' for r in new_n.values()),
                   moves=notes_diff['moves'], changed_rows=len(notes_diff['changed'])),
        restricted=dict(rows=len(new_r), moves=restricted_diff['moves'], changed_rows=len(restricted_diff['changed']),
                        counted_old=sum(float(r['counted_yuan'] or 0) for r in old_r.values() if r['status'] == 'ok'),
                        counted_new=sum(float(r['counted_yuan'] or 0) for r in new_r.values() if r['status'] == 'ok')),
        port_mismatches=port, digests={str(p.relative_to(ROOT)): digest(p) for p in NOTE_INPUTS['P']},
        production_digests={str(p.relative_to(ROOT)): digest(p) for p in (production_notes, production_restricted)})
    save('inputs_summary.json', dict(summary, notes_changed=notes_diff['changed'], restricted_changed=restricted_diff['changed']))
    print(json.dumps({k: v for k, v in summary.items() if k not in ('port_mismatches',)}, ensure_ascii=False, indent=1))
    print('port mismatches outside manual codes:', len(port))


if __name__ == '__main__':
    main()
