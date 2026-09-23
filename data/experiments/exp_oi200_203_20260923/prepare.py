"""Freeze stored states (full copies + panel subsets) and hash every build/backtest input."""
import os
import shutil
import subprocess
from common import EXP, ROOT, STATE_FILES, FROZEN_ACTIONS, digest, save, panel_codes, input_files


def main():
    assert not (EXP / 'before_manifest.json').exists(), 'never overwrite the frozen control'
    panel = panel_codes()
    subsets = {}
    for name in STATE_FILES:
        source = ROOT / 'data/processed' / name
        frozen = EXP / 'old_inputs/data/processed' / name
        subset = EXP / 'states/OLD' / name
        frozen.parent.mkdir(parents=True, exist_ok=True); subset.parent.mkdir(parents=True, exist_ok=True)
        rows = kept = 0
        with source.open('rb') as src, frozen.open('wb') as full, subset.open('wb') as sub:
            header = src.readline(); full.write(header); sub.write(header)
            for line in src:
                full.write(line); rows += 1
                if line.split(b',', 1)[0].decode().lstrip('﻿') in panel:
                    sub.write(line); kept += 1
        assert digest(frozen) == digest(source), name
        subsets[name] = dict(source=digest(source), rows=rows, panel_rows=kept, panel_subset=digest(subset))
        print('FROZEN', name, rows, kept, flush=True)
    FROZEN_ACTIONS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'data/raw/corporate_actions/a_share_corporate_actions.csv', FROZEN_ACTIONS)
    for rel in ('data/backtest/scan_summaries.csv', 'data/processed/daily_execution_publication.json'):
        dest = EXP / 'old_inputs' / rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dest)
    for p in (ROOT / 'data/backtest').glob('summary_BASE*.csv'):
        dest = EXP / 'old_inputs/data/backtest' / p.name; shutil.copyfile(p, dest)
    for p in (ROOT / 'data/processed').glob('a_share_pool_model_bands_*.csv'):
        dest = EXP / 'old_inputs/data/processed' / p.name; shutil.copyfile(p, dest)
    for rel in ('data/processed/a_share_core_valuation_pool.csv', 'data/processed/a_share_valuation_dossiers.csv',
                'data/processed/a_share_focus_watchlist_l1_l2_valuation.csv', 'data/processed/daily_buy_candidates.csv'):
        dest = EXP / 'old_inputs' / rel; shutil.copyfile(ROOT / rel, dest)
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in input_files()}
    inputs['frozen_actions'] = digest(FROZEN_ACTIONS)
    save('before_manifest.json', dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                                      job_id=os.getenv('SLURM_JOB_ID'), states=subsets, inputs=inputs,
                                      panel_codes=sorted(panel)))


if __name__ == '__main__':
    main()
