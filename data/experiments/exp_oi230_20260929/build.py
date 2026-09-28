"""OI-230 候选检验：只重跑 §6.7 第 3 步（银行保险覆盖）与持仓侧合成——候选侧／B2 建带不变，取冻结副本。

    python3 build.py      # 第一段并行：CONTROL、DC_K0（三侧）与 CONTROL_RAW、DC_RAW（候选侧）；
                          # 第二段：calibrate_k.py 在两个 RAW 臂上估 c、b、k；第三段：DC（k = k_DC，三侧）
"""
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from common import EXP, ROOT, bank_mode

OLD = EXP / 'old_inputs/data/processed'


def rebuild(arm: str, sides: tuple[str, ...]) -> str:
    out = EXP / 'states' / f'{arm}_build'
    out.mkdir(parents=True, exist_ok=True)
    for name in ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv'):
        if name.endswith('_b2.csv') and 'b2' not in sides:
            continue
        shutil.copyfile(OLD / name, out / name)
    for side in sides:
        suffix, state = ('', 'a_share_daily_states_adopted.csv') if side == 'base' else ('_b2', 'a_share_daily_states_b2.csv')
        with (EXP / f'build_{arm}_{side}_bank.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), bank_mode(arm), str(out / state),
                            str(out / f'roic_daily_raw{suffix}.csv'), str(out / f'roic_bands{suffix}.csv')],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True, env=dict(os.environ, PYTHONUNBUFFERED='1'))
    if 'b2' in sides:
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'),
                        '--base', str(out / 'a_share_daily_states_adopted.csv'), '--b2', str(out / 'a_share_daily_states_b2.csv'),
                        '--out', str(out / 'a_share_daily_states_hold.csv')], cwd=ROOT, check=True)
    print('DONE', arm, sides, flush=True)
    return arm


def main():
    first = [('CONTROL', ('base', 'b2')), ('DC_K0', ('base', 'b2')), ('CONTROL_RAW', ('base',)), ('DC_RAW', ('base',))]
    with ThreadPoolExecutor(max_workers=len(first)) as pool:
        list(pool.map(lambda job: rebuild(*job), first))
    subprocess.run([sys.executable, str(EXP / 'calibrate_k.py')], cwd=EXP, check=True)
    rebuild('DC', ('base', 'b2'))


if __name__ == '__main__':
    main()
