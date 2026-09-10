"""Verify unchanged prior inputs and freeze the registered adoption evaluation."""
from collections import Counter
from datetime import datetime
import os
from zoneinfo import ZoneInfo
import json
from common import EXP, ROOT, PRIOR, sw, grid, fingerprint, save


def main():
    previous=json.loads((PRIOR/'manifest.json').read_text())
    assert sw.BASE==previous['base'] and sw.DEFAULT_STARTS==previous['starts']
    prior_paths={ROOT/p for p in previous['inputs']}
    before=fingerprint(prior_paths)
    assert before==previous['inputs'],'Prior frozen source changed; cannot reuse baseline or equivalence'
    save('grid.json',grid())
    extras={EXP/p for p in ('common.py','engine.py','prepare_eval.py','run_eval.py','signals.py','preregister.md','grid.json')}
    extras|={ROOT/'scripts/experimental'/p for p in ('selection_edge_audit.py','swap_regime_control.py',
               'panel_tier_forward.py','delta_attribution.py','moat_param_lab.py')}
    extras.add(ROOT/'data/processed/a_share_watchlist_quality_tiers.csv')
    inputs={**before,**fingerprint(extras)}
    price_ends={}
    for code,old_end in previous['price_ends'].items():
        with (ROOT/f'data/raw/ohlcv/{code}.csv').open('rb') as f:
            header=f.readline().decode('utf-8-sig').strip().split(',')
            f.seek(0,2);f.seek(max(0,f.tell()-4096))
            last=f.read().decode().splitlines()[-1].split(',')
        end=last[header.index('date')]
        assert end==old_end,(code,end,old_end)
        price_ends[code]=end
    save('manifest.json',dict(started_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
         job_id=os.environ.get('SLURM_JOB_ID'),base=sw.BASE,starts=sw.DEFAULT_STARTS,metric=sw.METRIC_VERSION,
         inputs=inputs,prior_manifest='exp_equity_bond_opt_20260910/manifest.json',
         prior_inputs_identical=True,production_equivalence=previous['production_equivalence'],
         state_args=previous['state_args'],price_ends=price_ends,registry_arms=len(grid()),
         previous_trial_registry_arms=53,previous_new_candidates=50,earlier_family_arms=19))
    print('PREPARE COMPLETE: prior inputs unchanged; compact states equivalent; price ends',dict(Counter(price_ends.values())),flush=True)


if __name__=='__main__':
    main()
