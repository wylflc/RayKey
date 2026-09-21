"""Freeze OI-198 inputs and census every stored report, including signed zero."""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
FILES = ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv',
         'a_share_daily_states_adopted.csv', 'a_share_daily_states_b2.csv', 'a_share_daily_states_hold.csv')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return dict(bytes=path.stat().st_size, sha256=h.hexdigest())


def save(name, value):
    (EXP/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def main():
    assert not (EXP/'before_manifest.json').exists(), 'Never overwrite the frozen control'
    census = {}; targets = set()
    for name in FILES[:2]:
        codes = set(); negative = []; n = 0
        with (ROOT/'data/processed'/name).open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                n += 1; codes.add(row['security_code'])
                if row.get('minority_book_ps', '').startswith('-'):
                    negative.append({k: row[k] for k in ('security_code','report_date','available_at','status',
                        'roic_path','minority_book_ps','minority_share','net_debt_ps','fin_net_debt_ps','external_equity_ps')})
                    targets.add(row['security_code'])
        census[name] = dict(rows=n, codes=len(codes), negative_book_rows=negative,
                            negative_book_codes=sorted({r['security_code'] for r in negative}))
    save('census.json', census); save('repairs.json', dict(codes=sorted(targets)))
    panel = {r['security_code'] for r in read(ROOT/'data/processed/pit_attention/panel_moat_bank_v6b.csv')}
    results = {}
    for name in FILES:
        source = ROOT/'data/processed'/name
        frozen = EXP/'old_inputs/data/processed'/name
        subset = EXP/'states/OLD'/name; block = EXP/'states/old_blocks'/name
        for p in (frozen, subset, block): p.parent.mkdir(parents=True, exist_ok=True)
        full_h = hashlib.sha256(); panel_h = hashlib.sha256(); block_h = hashlib.sha256()
        n = p = t = 0; source_codes = set()
        with source.open('rb') as src, frozen.open('wb') as old, subset.open('wb') as out, block.open('wb') as sel:
            header = src.readline()
            for h, f in ((full_h, old), (panel_h, out), (block_h, sel)):
                h.update(header); f.write(header)
            for line in src:
                full_h.update(line); old.write(line); n += 1
                code = line.split(b',',1)[0].decode(); source_codes.add(code)
                if code in panel:
                    out.write(line); panel_h.update(line); p += 1
                if code in targets:
                    sel.write(line); block_h.update(line); t += 1
        assert digest(frozen)['sha256'] == full_h.hexdigest()
        assert digest(subset)['sha256'] == panel_h.hexdigest()
        assert digest(block)['sha256'] == block_h.hexdigest()
        results[name] = dict(source_sha256=full_h.hexdigest(), rows=n, panel_rows=p, target_rows=t,
            panel_sha256=panel_h.hexdigest(), target_sha256=block_h.hexdigest(),
            missing_panel_codes=sorted(panel-source_codes))
        # A panel interval without any historical quote may have no state rows;
        # absence is identical to the full source, never invented by extraction.
        print('FROZEN', name, n, p, t, flush=True)
    small = ['scripts/backtest_valuation_strategy.py','scripts/sweep_backtest_configs.py',
             'scripts/build_historical_valuation_bands.py','scripts/minority_claims.py',
             'scripts/corporate_actions.py','scripts/apply_forecast_band_overlay.py',
             'data/reference/cost_of_equity_inputs.csv','data/reference/equity_bond_csi300.csv',
             'data/reference/minority_claim_events.json','data/reference/a_share_exright_terms.csv',
             'data/reference/a_share_action_component_corrections.csv',
             'data/raw/corporate_actions/a_share_corporate_actions.csv',
             'data/processed/pit_attention/panel_moat_bank_v6b.csv','data/backtest/scan_summaries.csv',
             'data/processed/shadow_portfolio/since_20260828/manifest.json',
             'data/interim/daily_evidence_2026-09-21.json', 'docs/000_daily_scan_log.md']
    small += [str(p.relative_to(ROOT)) for p in (ROOT/'data/processed').glob('*.csv') if p.name not in FILES]
    small += ['data/processed/daily_execution_publication.json']
    small += [str(p.relative_to(ROOT)) for p in (ROOT/'data/backtest').glob('summary_BASE*.csv')]
    before = {}
    for name in dict.fromkeys(small):
        source = ROOT/name
        if not source.exists(): continue
        dest = EXP/'old_inputs'/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest); before[name] = digest(source)
        assert digest(dest) == before[name], name
    raw = {}; ends = {}
    for code in sorted(panel | targets):
        price = ROOT/f'data/raw/ohlcv/{code}.csv'
        if price.exists():
            with price.open('rb') as f:
                f.seek(0,2); f.seek(max(0,f.tell()-4096))
                ends[code] = f.read().decode().splitlines()[-1].split(',')[0]
            sources = [price]
        else:
            ends[code] = None; sources = []
        for source in sources:
            if not source.is_file(): continue
            name = str(source.relative_to(ROOT)); raw[name] = digest(source)
            dest = EXP/'old_inputs'/name; dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
    # These caches are organized by report/table, not by security code.
    for folder in ('financials', 'financials_statements'):
        for source in (ROOT/'data/raw'/folder).rglob('*.csv'):
            name = str(source.relative_to(ROOT)); raw[name] = digest(source)
            dest = EXP/'old_inputs'/name; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
    save('before_manifest.json',dict(revision=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),inputs=before,raw_inputs=raw))
    save('state_extracts.json',dict(job_id=os.getenv('SLURM_JOB_ID'),panel_codes=sorted(panel),targets=sorted(targets),
        panel_coverage='Every source row for every BASE panel code retained byte-for-byte', files=results,price_ends=ends))


if __name__ == '__main__': main()
