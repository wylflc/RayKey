"""Publish the guard-verified BASE summaries and merge them via the canonical ledger API (old BASE rows stay under the old name)."""
import csv
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import clean_derived_artifacts as ledger
import sweep_backtest_configs as sw
from ex_winner_symmetry import top5


def read(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def key(row):
    return row['扫描标签'], row['策略'], row['计量版本']


def main():
    verification = json.loads((EXP / 'verification.json').read_text())
    assert verification['track_a_pass'] and verification['inputs_unchanged'] and verification['negative_cash_days'] == 0
    assert verification['complete_start_and_window_sets'] and verification['base_paths'] == 28
    rows = [r for r in read(EXP / 'summary_rows.csv') if r['arm'] == 'BASE' and r['group'] in ('full', 'A')]
    assert len(rows) == 28
    for group in ('full', 'A'):
        assert sorted(r['start'] for r in rows if r['group'] == group) == sorted(sw.DEFAULT_STARTS)
    winners = json.loads((EXP / 'guardrail.json').read_text())['winners_new']
    sources = []
    for row in rows:
        source = EXP / 'cache' / row['group'] / f"summary_{row['nav_tag']}.csv"
        clean = {k: v for k, v in row.items() if k not in ('group', 'arm', 'start', 'nav_tag', 'guard_skips')}
        assert read(source) == [clean], source
        assert '_cap0.6s_' in clean['策略'] and clean['计量版本'] == sw.METRIC_VERSION
        sources.append(source)
    before = {key(r): r for r in read(ledger.MERGED)}
    published = []
    for source in sources:
        target = sw.OUT_DIR / source.name
        old_sha = sha(target)
        temporary = target.with_name(f'.{target.name}.oi167.{os.getpid()}')
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        assert sha(target) == sha(source)
        published.append(dict(path=str(target.relative_to(ROOT)), before_sha256=old_sha, after_sha256=sha(target)))
    names = {p.name for p in sources}
    with os.scandir(sw.OUT_DIR) as entries:
        update = ledger.write_ledger([e for e in entries if e.name in names])
    after = {key(r): r for r in read(ledger.MERGED)}
    assert before.keys() <= after.keys() and all(after[k] == v for k, v in before.items()), 'old ledger rows changed'
    expected = {(r['nav_tag'], r['策略'], r['计量版本']) for r in rows}
    assert after.keys() - before.keys() == expected, after.keys() - before.keys()
    assert top5('BASE', sw.EX5_ANCHOR_START) == winners or sorted(top5('BASE', sw.EX5_ANCHOR_START)) == sorted(winners)
    result = dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(), registered_base_rows=28,
                  canonical_summaries_refreshed=28, ledger_rows_before=len(before), ledger_rows_after=len(after),
                  newly_added_keys=len(after.keys() - before.keys()), old_rows_preserved=True, strategy_marker='_cap0.6s_',
                  anchor_winners=winners, entry_point='clean_derived_artifacts.write_ledger', published=published,
                  ledger_sha256=sha(ledger.MERGED), arm_index_rows=len(update.arms))
    (EXP / 'registration.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Registered 28 BASE summaries ({result['newly_added_keys']} new ledger keys); old rows intact.")


if __name__ == '__main__':
    main()
