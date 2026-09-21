"""Run old/new valuation implementations against frozen financial inputs, serially."""
import csv
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import types

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT/'scripts'))

if len(sys.argv) > 1:
    arm, side, task = sys.argv[1:4]
    actions = EXP/('old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv' if arm == 'OLD' else 'actions_corrected.csv')
    folder = EXP/'states'/f'{arm}_build'; folder.mkdir(exist_ok=True)
    suffix = '_b2' if side == 'b2' else ''
    raw = folder/f'roic_daily_raw{suffix}.csv'; bands = folder/f'roic_bands{suffix}.csv'
    if task == 'bands':
        path = ROOT/'scripts/build_historical_valuation_bands.py'
        source = EXP/'old_inputs/scripts/build_historical_valuation_bands.py' if arm == 'OLD' else path
        module = types.ModuleType('oi196_build'); module.__file__ = str(path); sys.modules[module.__name__] = module
        exec(compile(source.read_bytes(), str(source), 'exec'), module.__dict__)
        module.ACTIONS = actions
        module.STMT_GAP_LOG = folder/f'gaps{suffix}.csv'
        codes = json.loads((EXP/'repairs.json').read_text())['codes']
        sys.argv = ['build', '--codes', ','.join(codes), '--value-model', 'roic', '--roe-source', 'onesided_max', '--roe-lift', '2.0',
                    '--uniform-tier', 'L2', '--since', '2002-01-01', '--roic-nopat-source', 'conditional3', '--roic-growth', 'hybrid',
                    '--roic-cycle-guard', 'peak', '--roic-cond-detect', 'graded', '--roic-peak-ramp', '0.3', '--ttm-current', 'on',
                    '--growth-damp', 'on', '--thin-equity-max', '0.5', '--roic-trail-weight', '0', '--minority-basis', 'earnings',
                    '--wc-aggregation', 'operating', '--out-bands', str(bands), '--out-daily', str(raw)]
        if suffix: sys.argv += ['--ttm-trust', 'on', '--ttm-trust-delta', '0.02']
        raise SystemExit(module.main())
    if task == 'bank':
        import build_historical_valuation_bands as valuation
        valuation.ACTIONS = actions
        import divspread_dividend as div
        original = div.load_distributions
        div.load_distributions = lambda *a, **k: original(actions)
        output = folder/('a_share_daily_states_b2.csv' if suffix else 'a_share_daily_states_adopted.csv')
        sys.argv = ['bank', 'divspread:0.02', str(output), str(raw), str(bands)]
        runpy.run_path(str(ROOT/'scripts/rebuild_bank_bands.py'), run_name='__main__')
else:
    for arm in ('OLD', 'NEW'):
        for side in ('base', 'b2'):
            for task in ('bands', 'bank'):
                log = EXP/f'build_{arm}_{side}_{task}.log'
                with log.open('w') as f:
                    subprocess.run([sys.executable, __file__, arm, side, task], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True)
                print('BUILT', arm, side, task, flush=True)
        folder = EXP/'states'/f'{arm}_build'
        subprocess.run([sys.executable, str(ROOT/'scripts/build_hold_daily_states.py'), '--base', str(folder/'a_share_daily_states_adopted.csv'),
                        '--b2', str(folder/'a_share_daily_states_b2.csv'), '--out', str(folder/'a_share_daily_states_hold.csv')], check=True)
