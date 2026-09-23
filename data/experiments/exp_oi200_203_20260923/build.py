"""Full-market rebuilds for CONTROL / MID / NEW on frozen inputs (§6.7 steps 2, 2b, 3).

    python3 build.py                      # orchestrate: six band builds in parallel, then bank override, then hold states
    python3 build.py <ARM> <side> bands   # one builder process (side = base | b2)
    python3 build.py <ARM> <side> bank    # bank/insurer dividend override for that arm/side
"""
import os
import runpy
import subprocess
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import ARMS, B2, EXP, FLAGS, FROZEN_ACTIONS, PRODUCTION, ROOT

sys.path.insert(0, str(ROOT / 'scripts'))


def folder(arm: str) -> Path:
    path = EXP / 'states' / f'{arm}_build'
    path.mkdir(parents=True, exist_ok=True)
    return path


def child(arm: str, side: str, task: str) -> None:
    suffix = '_b2' if side == 'b2' else ''
    out = folder(arm)
    raw, bands = out / f'roic_daily_raw{suffix}.csv', out / f'roic_bands{suffix}.csv'
    import roic_inputs
    import restatement_archive
    if arm == 'CONTROL':
        # 改前口径：关闭 OI-200 类金融识别与客户资金扣除、OI-203 原文版本表与公告重述日
        roic_inputs.CLIENT_FUND_FIELDS = ()
        roic_inputs.FINANCIAL_INTERMEDIATION_MIN = float('inf')
        empty = out / 'no_filing_originals.csv'
        empty.write_text('security_code,report_date,superseded_at,original_url\n', encoding='utf-8')
        restatement_archive.FILING_ORIGINALS = empty
        roic_inputs.RESTATE_ANNOUNCEMENTS = None
    if task == 'bands':
        path = ROOT / 'scripts/build_historical_valuation_bands.py'
        module = types.ModuleType('exp_build'); module.__file__ = str(path)
        sys.modules[module.__name__] = module
        exec(compile(path.read_text(encoding='utf-8'), str(path), 'exec'), module.__dict__)
        module.ACTIONS = FROZEN_ACTIONS
        module.STMT_GAP_LOG = out / f'gaps{suffix}.csv'
        sys.argv = ['build', *PRODUCTION, *FLAGS[arm], *(B2 if suffix else []), '--out-bands', str(bands), '--out-daily', str(raw)]
        raise SystemExit(module.main())
    if task == 'bank':
        import build_historical_valuation_bands as valuation
        valuation.ACTIONS = FROZEN_ACTIONS
        import divspread_dividend as div
        original = div.load_distributions
        div.load_distributions = lambda *a, **k: original(FROZEN_ACTIONS)
        output = out / ('a_share_daily_states_b2.csv' if suffix else 'a_share_daily_states_adopted.csv')
        sys.argv = ['bank', 'divspread:0.02', str(output), str(raw), str(bands)]
        runpy.run_path(str(ROOT / 'scripts/rebuild_bank_bands.py'), run_name='__main__')


def run(arm: str, side: str, task: str) -> str:
    log = EXP / f'build_{arm}_{side}_{task}.log'
    with log.open('w') as f:
        subprocess.run([sys.executable, __file__, arm, side, task], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                       env=dict(os.environ, PYTHONUNBUFFERED='1', OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1'), check=True)
    print('DONE', arm, side, task, flush=True)
    return log.name


def orchestrate() -> None:
    arms = [a for a in os.environ.get('EXP_ARMS', ','.join(ARMS)).split(',') if a]
    jobs = [(a, s) for a in arms for s in ('base', 'b2')]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        list(pool.map(lambda j: run(*j, 'bands'), jobs))
        list(pool.map(lambda j: run(*j, 'bank'), jobs))
    for arm in arms:
        out = folder(arm)
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'),
                        '--base', str(out / 'a_share_daily_states_adopted.csv'), '--b2', str(out / 'a_share_daily_states_b2.csv'),
                        '--out', str(out / 'a_share_daily_states_hold.csv')], cwd=ROOT, check=True)
        print('DONE', arm, 'hold', flush=True)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(*sys.argv[1:4])
    else:
        orchestrate()
