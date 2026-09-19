"""Splice rebuilt 000022 bands/states into production files and rebuild hold-side states (OI-192)."""
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
CODE = '000022'
TARGETS = [  # (production file, rebuilt block)
    ('data/processed/roic_daily_raw.csv', 'states/roic_daily_raw_000022.csv'),
    ('data/processed/a_share_daily_states_adopted.csv', 'states/roic_daily_raw_000022.csv'),
    ('data/processed/roic_daily_raw_b2.csv', 'states/roic_daily_raw_000022_b2.csv'),
    ('data/processed/a_share_daily_states_b2.csv', 'states/roic_daily_raw_000022_b2.csv'),
    ('data/processed/roic_bands.csv', 'states/roic_bands_000022.csv'),
    ('data/processed/roic_bands_b2.csv', 'states/roic_bands_000022_b2.csv'),
]
HOLD = ROOT / 'data/processed/a_share_daily_states_hold.csv'


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


def splice(target, block_path):
    """Replace the CODE block in `target` with rows from `block_path`, aligned to the target header."""
    with open(block_path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        block_fields = reader.fieldnames
        block_rows = [r for r in reader if r['security_code'] == CODE]
    tmp = target.with_name('.' + target.name + '.oi192')
    other = hashlib.sha256()
    removed = inserted = 0
    written_block = False
    with open(target, newline='', encoding='utf-8') as src, open(tmp, 'w', newline='', encoding='utf-8') as dst:
        header = src.readline()
        fields = header.lstrip('\ufeff').rstrip('\r\n').split(',')   # bands files carry a BOM; header line itself is copied verbatim
        missing = [c for c in fields if c not in block_fields]
        assert not missing, (target.name, 'rebuilt block lacks columns', missing)
        extra = [c for c in block_fields if c not in fields]
        assert all(not r[c] for r in block_rows for c in extra), (target.name, 'non-empty extra columns', extra)
        dst.write(header)
        terminator = '\r\n' if header.endswith('\r\n') else '\n'   # keep the file's own convention (csv default is CRLF)
        writer = csv.DictWriter(dst, fieldnames=fields, extrasaction='ignore', lineterminator=terminator)
        prefix = CODE + ','
        for line in src:
            if line.startswith(prefix):
                removed += 1
                if not written_block:
                    writer.writerows(block_rows)
                    inserted = len(block_rows)
                    written_block = True
                continue
            other.update(line.encode('utf-8'))
            if not written_block and line.split(',', 1)[0] > CODE:  # block absent: insert in code order
                writer.writerows(block_rows)
                inserted = len(block_rows)
                written_block = True
            dst.write(line)
        if not written_block:
            writer.writerows(block_rows)
            inserted = len(block_rows)
    # other-rows hash of the new file must equal the old one (only the CODE block changed)
    check = hashlib.sha256()
    with open(tmp, newline='', encoding='utf-8') as f:
        f.readline()
        for line in f:
            if not line.startswith(prefix):
                check.update(line.encode('utf-8'))
    assert check.hexdigest() == other.hexdigest(), target.name
    os.replace(tmp, target)
    return dict(removed=removed, inserted=inserted, other_rows_sha256=other.hexdigest(), header_columns=len(fields), dropped_empty_columns=extra, line_terminator=repr(terminator))


def block_rows(path, code):
    out = {}
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if r['security_code'] == code:
                out[r['date']] = r
            elif out:
                break
    return out


def main():
    started = datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()
    before = {t: sha(ROOT / t) for t, _ in TARGETS}
    before['data/processed/a_share_daily_states_hold.csv'] = sha(HOLD)
    results = {}
    for target, block in TARGETS:
        results[target] = splice(ROOT / target, EXP / block)
        print('SPLICED', target, results[target], flush=True)
    hold_before = sum(1 for _ in open(HOLD, encoding='utf-8'))
    cmd = [sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'), '--base', 'data/processed/a_share_daily_states_adopted.csv',
           '--b2', 'data/processed/a_share_daily_states_b2.csv', '--out', 'data/processed/a_share_daily_states_hold.csv']
    hold_log = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (EXP / 'hold_rebuild.log').write_text(hold_log.stdout + hold_log.stderr)
    assert hold_log.returncode == 0, hold_log.stderr[-2000:]
    hold_after = sum(1 for _ in open(HOLD, encoding='utf-8'))
    # validation: rebuilt 000022 vs 001872 inside the panel window (same entity, same inputs)
    new = block_rows(ROOT / 'data/processed/a_share_daily_states_adopted.csv', CODE)
    ref = block_rows(ROOT / 'data/processed/a_share_daily_states_adopted.csv', '001872')
    keys = [k for k in new if '2005-04-30' <= k <= '2016-04-30']
    same_band = [k for k in keys if new[k]['band_report_date'] == ref[k]['band_report_date']]
    rel = max(abs(float(new[k]['intrinsic_value']) / float(ref[k]['intrinsic_value']) - 1) for k in same_band)
    split_eq = sum(new[k]['split_factor'] == ref[k]['split_factor'] for k in new if k <= '2018-12-20')
    hold_rows = block_rows(HOLD, CODE)
    validation = dict(started_beijing=started, job_id=os.getenv('SLURM_JOB_ID'), before_sha256=before,
                      notes='job 26921419 already spliced the four daily-state files before failing on the bands BOM header; before_sha256 of those four is the post-splice value, originals: old_inputs/SHA256SUMS (adopted, hold) and log other_rows_sha256',
                      after_sha256={t: sha(ROOT / t) for t, _ in TARGETS} | {'data/processed/a_share_daily_states_hold.csv': sha(HOLD)},
                      splice=results, hold_rows_before=hold_before, hold_rows_after=hold_after,
                      hold_000022_rows=len(hold_rows), hold_000022_sources={s: sum(1 for r in hold_rows.values() if r['hold_source'] == s) for s in ('base', 'b2')},
                      panel_window_rows=len(keys), same_band_rows=len(same_band), max_rel_dV_same_band=rel,
                      split_factor_equal_to_001872=[split_eq, sum(1 for k in new if k <= '2018-12-20')],
                      rebuilt_rows=len(new))
    assert rel <= 1e-3 and split_eq == validation['split_factor_equal_to_001872'][1], validation
    assert hold_after == hold_before and len(hold_rows) == len(new), validation
    (EXP / 'states_validation.json').write_text(json.dumps(validation, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
