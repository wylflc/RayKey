"""Publish verified native BASE summaries and merge via the canonical ledger API."""
import csv
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
    assert verification['native_base_paths'] == 28 and verification['legacy_anchor_paths'] == 2
    for field in ('all_decision_and_standard_fields_exact', 'summary_equivalent_with_descriptive_rounding',
                  'exact_nav_cash_debt_positions_weights', 'complete_start_and_window_sets',
                  'base_us_unchanged', 'inputs_unchanged'):
        assert verification[field], field
    assert verification['negative_cash_days'] == 0
    assert verification['live_signal_observations_identical'] == 258
    assert json.loads((EXP / 'manifest.json').read_text())['base'] == sw.BASE
    rows = [r for r in read(EXP / 'summary_rows.csv') if r['arm'] == 'BASE']
    assert len(rows) == 28
    for group in ('full', 'A'):
        assert sorted(r['start'] for r in rows if r['group'] == group) == sorted(sw.DEFAULT_STARTS)

    sources = []
    for row in rows:
        source = EXP / 'cache' / row['group'] / f"summary_{row['nav_tag']}.csv"
        clean = {k: v for k, v in row.items() if k not in ('group', 'arm', 'start', 'nav_tag')}
        assert read(source) == [clean], source
        assert '_c0.3h0.035_' in clean['策略'] and clean['计量版本'] == sw.METRIC_VERSION
        sources.append(source)

    before = {key(r): r for r in read(ledger.MERGED)}
    planned = ledger.write_ledger(
        [entry for directory in ('full', 'A') for entry in os.scandir(EXP / 'cache' / directory)
         if Path(entry.path) in sources], apply=False)
    # The ledger uses a union schema and writes absent legacy columns as blanks.
    preview = {key(r): {col: r.get(col, '') for col in planned.current_columns} for r in planned.current}
    assert before.keys() <= preview.keys()
    assert all(preview[k] == v for k, v in before.items())
    expected = {(r['nav_tag'], r['策略'], r['计量版本']) for r in rows}
    assert expected <= preview.keys()
    assert preview.keys() - before.keys() <= expected

    # Standard summary readers prefer these files; refresh them with the verified
    # native outputs, as sweep_backtest_configs.run_one does after each run.
    published = []
    for source in sources:
        target = sw.OUT_DIR / source.name
        old_sha = sha(target)
        temporary = target.with_name(f'.{target.name}.c030r35.{os.getpid()}')
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
        assert sha(target) == sha(source)
        published.append(dict(path=str(target.relative_to(ROOT)), before_sha256=old_sha,
                              after_sha256=sha(target)))
    names = {p.name for p in sources}
    with os.scandir(sw.OUT_DIR) as entries:
        update = ledger.write_ledger([e for e in entries if e.name in names])
    after = {key(r): r for r in read(ledger.MERGED)}
    assert after == preview and all(after[k] == v for k, v in before.items())
    reference_commit = json.loads((EXP / 'manifest.json').read_text())['reference_commit']
    frozen_text = subprocess.check_output(
        ['git', 'show', f'{reference_commit}:{ledger.MERGED.relative_to(ROOT)}'], cwd=ROOT, text=True)
    frozen = {key(r): r for r in csv.DictReader(io.StringIO(frozen_text))}
    assert frozen.keys() <= after.keys()
    assert all(all(after[k].get(col, '') == value for col, value in r.items()) for k, r in frozen.items())
    assert after.keys() - frozen.keys() == expected
    anchor = next(r for r in rows if r['group'] == 'full' and r['start'] == sw.EX5_ANCHOR_START)
    winners = anchor[sw.EX5_FIELD].split('/')
    assert top5('BASE', sw.EX5_ANCHOR_START) == winners
    # Verify fallback selection after routine summary cleanup without deleting any file.
    fallback = [r for r in read(ledger.MERGED) if r['扫描标签'] == anchor['nav_tag']
                and r['计量版本'] == sw.METRIC_VERSION and r['策略'].startswith('trend_')][-1]
    assert fallback['策略'] == anchor['策略'] and fallback[sw.EX5_FIELD].split('/') == winners
    result = dict(completed_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                  registered_base_rows=28, canonical_summaries_refreshed=28,
                  ledger_rows_before=len(before), ledger_rows_after=len(after),
                  newly_added_keys=len(after.keys() - before.keys()), old_rows_preserved=True,
                  frozen_ledger_commit=reference_commit, frozen_ledger_rows=len(frozen),
                  added_keys_vs_frozen_ledger=len(after.keys() - frozen.keys()),
                  native_strategy_marker='_c0.3h0.035_', anchor_winners=winners,
                  winner_reader_and_ledger_fallback_verified=True,
                  entry_point='clean_derived_artifacts.write_ledger', published=published,
                  ledger_sha256=sha(ledger.MERGED), arm_index_rows=len(update.arms))
    (EXP / 'registration.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Registered 28 native BASE summaries; {result['newly_added_keys']} new ledger keys; old rows intact.")


if __name__ == '__main__':
    main()
