"""Re-register BASE full/A summaries from the NEW arm (inputs-only change; same keys overwritten per OI-168 precedent)."""
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
import clean_derived_artifacts as ledger


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    v = json.loads((EXP / 'verification.json').read_text())
    assert v['complete_pairing'] and v['zero_negative_cash'] and v['track_a_pass']
    winners = json.loads((EXP / 'winners.json').read_text())
    exclude_A = ','.join(winners['A'])
    rows = [r for r in read(EXP / 'summary_rows.csv') if r['arm'] == 'NEW' and r['group'] in ('full', 'A')]
    assert len(rows) == 28
    key = lambda r: (r['扫描标签'], r['策略'], r['计量版本'])
    before = {key(r): r for r in read(ledger.MERGED)}
    committed_csv = subprocess.check_output(['git', 'show', 'HEAD:data/backtest/scan_summaries.csv'], cwd=ROOT, text=True)
    committed = {key(r): r for r in csv.DictReader(io.StringIO(committed_csv))}
    paths, published, touched = [], [], set()
    for r in rows:
        tag = sw.summary_tag('BASE', r['start'], exclude_A if r['group'] == 'A' else '')
        clean = {k: x for k, x in r.items() if k not in ('group', 'arm', 'start', 'bp', 'tag')}
        suffix = '_' + r['tag']; assert clean['策略'].endswith(suffix)
        clean['策略'] = clean['策略'][:-len(suffix)] + '_' + tag
        target = sw.OUT_DIR / f'summary_{tag}.csv'
        old = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        tmp = target.with_name('.' + target.name + '.oi192')
        with tmp.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(clean)); w.writeheader(); w.writerow(clean)
        tmp.replace(target); paths.append(target); touched.add((tag, clean['策略'], clean['计量版本']))
        published.append(dict(path=str(target.relative_to(ROOT)), before_sha256=old, after_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    names = {p.name for p in paths}
    with os.scandir(sw.OUT_DIR) as it:
        entries = [e for e in it if e.name in names]
    ledger.write_ledger(entries)
    after = {key(r): r for r in read(ledger.MERGED)}
    assert before.keys() <= after.keys(), '旧键不得删除'
    assert touched <= after.keys() and len(touched) == 28
    untouched = {k: r for k, r in committed.items() if k not in touched}
    assert untouched.keys() <= after.keys() and all(after[k] == r for k, r in untouched.items()), '本批之外的已登记行不得改写'
    overwritten = sum(1 for k in touched if k in committed)
    (EXP / 'registration.json').write_text(json.dumps(dict(registered_base_rows=28, overwritten_keys=overwritten, new_keys=len(after) - len(before),
        input_epoch='code_succession_20260919', precedent='OI-168 §12.217 同键重登', final_job=os.getenv('OI192_JOB', ''),
        entry_point='clean_derived_artifacts.write_ledger', published=published), ensure_ascii=False, indent=2) + '\n')
    print(f'REGISTERED 28 BASE summaries (overwritten {overwritten}); other ledger rows preserved.')


if __name__ == '__main__':
    main()
