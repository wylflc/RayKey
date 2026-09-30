"""按 §6.7 第 2／2b／3 步原命令在实验目录重建逐日状态（行情读 `ohlcv/`），再截出面板子集。

    python3 build.py            # 两侧建带并行 → 两侧银行保险覆盖并行 → 持仓侧合成 → 面板子集
    python3 build.py side base  # 单侧建带（由上一行调用）
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import B2, BANK_MODE, OHLCV, PANEL_STATES, PRODUCTION, ROOT, STATES, build_codes, panel_codes

STATE = {'base': 'a_share_daily_states_adopted.csv', 'b2': 'a_share_daily_states_b2.csv'}
SUFFIX = {'base': '', 'b2': '_b2'}


def side(name: str) -> int:
    os.environ['RK_STMT_GAP_LOG'] = str(STATES / f'valuation_statement_gaps{SUFFIX[name]}.csv')
    import build_historical_valuation_bands as bands
    bands.OHLCV_DIR = OHLCV
    bands.MARKET_CALENDAR = OHLCV / 'INDEX_000001.csv'
    sys.argv = ['build_historical_valuation_bands.py', '--codes-file', str(STATES / 'codes.txt'), *PRODUCTION,
                *(B2 if name == 'b2' else []),
                '--out-bands', str(STATES / f'roic_bands{SUFFIX[name]}.csv'),
                '--out-daily', str(STATES / f'roic_daily_raw{SUFFIX[name]}.csv')]
    return bands.main()


def call(args: list[str], log: str) -> None:
    with (STATES / log).open('w') as f:
        subprocess.run(args, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, check=True,
                       env=dict(os.environ, PYTHONUNBUFFERED='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))


def bank(name: str) -> None:
    call([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), BANK_MODE, str(STATES / STATE[name]),
          str(STATES / f'roic_daily_raw{SUFFIX[name]}.csv'), str(STATES / f'roic_bands{SUFFIX[name]}.csv')],
         f'bank_{name}.log')


def subset(name: str, panel: set[str]) -> None:
    kept = 0
    with (STATES / name).open('rb') as src, (PANEL_STATES / name).open('wb') as out:
        out.write(src.readline())
        for line in src:
            if line.split(b',', 1)[0].decode() in panel:
                out.write(line)
                kept += 1
    print('SUBSET', name, kept, flush=True)


def main():
    STATES.mkdir(parents=True, exist_ok=True)
    PANEL_STATES.mkdir(parents=True, exist_ok=True)
    (STATES / 'codes.txt').write_text('\n'.join(build_codes()) + '\n')
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda s: call([sys.executable, str(Path(__file__).resolve()), 'side', s], f'build_{s}.log'), ('base', 'b2')))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(bank, ('base', 'b2')))
    call([sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'), '--base', str(STATES / STATE['base']),
          '--b2', str(STATES / STATE['b2']), '--out', str(STATES / 'a_share_daily_states_hold.csv')], 'hold.log')
    panel = panel_codes()
    for name in ('a_share_daily_states_adopted.csv', 'a_share_daily_states_hold.csv'):
        subset(name, panel)


if __name__ == '__main__':
    if sys.argv[1:2] == ['side']:
        raise SystemExit(side(sys.argv[2]))
    main()
