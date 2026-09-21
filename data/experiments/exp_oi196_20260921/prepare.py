"""OI-196: verified corrections and byte-equivalent panel/target state extracts."""
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from corporate_actions import ACTION_FIELDS, aggregate_actions, unique_actions

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}

def save(name, value):
    (EXP / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def write(path, rows, fields=ACTION_FIELDS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    audit = json.loads((EXP/'component_audit.json').read_text())
    groups = next(v for v in audit.values() if isinstance(v, list))
    repairs = [g for g in groups if g['security_code'] != '600080']
    assert len(repairs) == 12
    codes = sorted({g['security_code'] for g in repairs})
    old = read(EXP/'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv')
    keys = {(g['security_code'], g['ex_dividend_date']) for g in repairs}
    kept = [r for r in old if (r['security_code'], r['ex_dividend_date']) not in keys or float(r['rights_ratio'] or 0)]
    new = unique_actions(kept + [r for g in repairs for r in g['source_components']])
    assert len(new) == len(old) + 12
    write(EXP/'actions_corrected.csv', new)
    save('repairs.json', dict(codes=codes, groups=repairs, old_rows=len(old), new_rows=len(new),
                             new_daily_events=[r for r in aggregate_actions(new) if (r['security_code'], r['ex_dividend_date']) in keys],
                             source_exclusion='600080 1997-08-19: one actual 10-for-6 capitalization; see reference exclusion'))
    panel = read(ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv')
    universe = {r['security_code'] for r in panel}
    results = {}
    for name in ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv',
                 'a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv'):
        source = ROOT/'data/processed'/name
        dest = EXP/'states/OLD'/name
        block = EXP/'states/old_blocks'/name
        dest.parent.mkdir(parents=True, exist_ok=True); block.parent.mkdir(parents=True, exist_ok=True)
        full = hashlib.sha256(); selected = hashlib.sha256(); targets = hashlib.sha256()
        n = p = t = 0
        with source.open('rb') as src, dest.open('wb') as out, block.open('wb') as target:
            header = src.readline(); full.update(header); selected.update(header); targets.update(header)
            out.write(header); target.write(header)
            for line in src:
                full.update(line); n += 1
                code = line.split(b',', 1)[0].decode()
                if code in universe:
                    out.write(line); selected.update(line); p += 1
                if code in codes:
                    target.write(line); targets.update(line); t += 1
        assert digest(dest)['sha256'] == selected.hexdigest()
        assert digest(block)['sha256'] == targets.hexdigest()
        results[name] = dict(source_sha256=full.hexdigest(), rows=n, panel_rows=p, target_rows=t,
                             panel_sha256=selected.hexdigest(), target_sha256=targets.hexdigest())
        print('EXTRACT', name, p, t, flush=True)
    ends = {}
    for code in sorted(universe | set(codes)):
        path = ROOT/f'data/raw/ohlcv/{code}.csv'
        if not path.exists():
            ends[code] = None; continue
        with path.open('rb') as f:
            f.seek(0, 2); f.seek(max(0, f.tell()-4096))
            ends[code] = f.read().decode().splitlines()[-1].split(',')[0]
    save('state_extracts.json', dict(job_id=os.getenv('SLURM_JOB_ID'), panel_codes=sorted(universe), targets=codes,
                                  panel_coverage='all rows for every BASE panel code, source bytes retained and hashes verified',
                                  files=results, price_ends=ends))

if __name__ == '__main__':
    main()
