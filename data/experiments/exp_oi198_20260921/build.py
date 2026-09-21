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
    import corporate_actions as ca
    ca.PRICE_TERMS_PATH = ROOT/'data/reference/a_share_exright_terms.csv'
    actions = EXP/'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
    folder = EXP/'states'/f'{arm}_build'; folder.mkdir(exist_ok=True)
    if os.getenv('EXP_CHUNK'):
        folder = folder/'chunks'/f"{side}_{os.environ['EXP_CHUNK']}"; folder.mkdir(parents=True, exist_ok=True)
    suffix = '_b2' if side == 'b2' else ''
    raw = folder/f'roic_daily_raw{suffix}.csv'; bands = folder/f'roic_bands{suffix}.csv'
    if task == 'bands':
        path = ROOT/'scripts/build_historical_valuation_bands.py'
        source = path
        module = types.ModuleType('oi198_build'); module.__file__ = str(path); sys.modules[module.__name__] = module
        # Only the frozen historical control may use the pre-7bd97bef bridge.
        # NEW executes production source unchanged and needs no compatibility keys.
        source_text = source.read_text()
        needle = '                return minority_claims.equity_bridge(\n'
        assert source_text.count(needle) == 1
        legacy = '''                if (code, period) in OI198_LEGACY_BRIDGE_KEYS:
                    assert claim_snapshot is None
                    minority_ps, proportional = minority_book_ps, 0.0
                    if minority_basis == "earnings" and m_share > 0:
                        total_equity_ps = ev_value - fin_net_debt_ps
                        if total_equity_ps > 0:
                            by_earnings = m_share * total_equity_ps
                            if by_earnings > minority_book_ps:
                                minority_ps, proportional = by_earnings, by_earnings
                    nd = fin_net_debt_ps + minority_ps - x_ps
                    return nd, nd - proportional
'''
        if arm == 'LEGACY':
            name = 'roic_bands_b2.csv' if suffix else 'roic_bands.csv'
            candidates = json.loads((EXP/'census.json').read_text())[name]['negative_book_rows']
            keys = {(r['security_code'], r['report_date']) for r in candidates}
        elif arm == 'OLD':
            keys = {tuple(k) for k in json.loads((EXP/'legacy_bridge_keys.json').read_text())[side]}
        else:
            keys = set()
        module.OI198_LEGACY_BRIDGE_KEYS = keys
        if arm != 'NEW':
            source_text = source_text.replace(needle, legacy + needle)
        exec(compile(source_text, str(source), 'exec'), module.__dict__)
        module.ACTIONS = actions
        module.STMT_GAP_LOG = folder/f'gaps{suffix}.csv'
        codes = json.loads(os.environ['EXP_CODES']) if os.getenv('EXP_CODES') else json.loads((EXP/'repairs.json').read_text())['codes']
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
    from concurrent.futures import ThreadPoolExecutor
    import heapq
    codes = json.loads((EXP/'repairs.json').read_text())['codes']
    workers = min(8, int(os.environ['SLURM_CPUS_PER_TASK']))
    chunks = [codes[i::workers] for i in range(workers)]
    def one(job):
        arm, side, idx, selected = job
        env = dict(os.environ, EXP_CHUNK=str(idx), EXP_CODES=json.dumps(selected), PYTHONUNBUFFERED='1')
        log = EXP/f'build_{arm}_{side}_chunk{idx}.log'
        with log.open('w') as f:
            subprocess.run([sys.executable, __file__, arm, side, 'bands'], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=env, check=True)
        return idx
    def merge(arm, side, name):
        folder = EXP/'states'/f'{arm}_build'
        handles = [(folder/'chunks'/f'{side}_{i}'/name).open('rb') for i in range(workers)]
        try:
            headers = [f.readline() for f in handles]; assert len(set(headers)) == 1, (name, headers)
            with (folder/name).open('wb') as out:
                out.write(headers[0])
                for line in heapq.merge(*handles, key=lambda line:line.split(b',',1)[0]): out.write(line)
        finally:
            for handle in handles: handle.close()
    for arm in (('OLD',) if os.getenv('RESUME_CONTROL') == '1' else ('NEW', 'LEGACY', 'OLD')):
        if arm == 'OLD':
            from classify import main as classify
            classify()
        for side in ('base', 'b2'):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                list(pool.map(one, [(arm,side,i,c) for i,c in enumerate(chunks)]))
            suffix = '_b2' if side == 'b2' else ''
            for name in (f'roic_bands{suffix}.csv',f'roic_daily_raw{suffix}.csv'): merge(arm,side,name)
            print('BUILT',arm,side,'bands',flush=True)
            with (EXP/f'build_{arm}_{side}_bank.log').open('w') as f:
                subprocess.run([sys.executable,__file__,arm,side,'bank'],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
            print('BUILT',arm,side,'bank',flush=True)
        folder=EXP/'states'/f'{arm}_build'
        subprocess.run([sys.executable,str(ROOT/'scripts/build_hold_daily_states.py'),'--base',str(folder/'a_share_daily_states_adopted.csv'),
                        '--b2',str(folder/'a_share_daily_states_b2.csv'),'--out',str(folder/'a_share_daily_states_hold.csv')],check=True)
