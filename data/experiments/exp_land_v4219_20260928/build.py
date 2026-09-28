"""v4.219 落地：只重跑 §6.7 第 3 步（银行保险覆盖）与持仓侧合成——候选侧／B2 建带不变，取冻结副本。

    python3 build.py      # CONTROL（h2:0.02:0.10:1）与 BK（h2:0.02:0.10:0.6951）两臂 → states/<臂>_build/ 七份文件
"""
import os
import shutil
import subprocess
import sys

from common import ARMS, BANK_MODE, EXP, ROOT

OLD = EXP / 'old_inputs/data/processed'


def main():
    for arm in ARMS:
        out = EXP / 'states' / f'{arm}_build'
        out.mkdir(parents=True, exist_ok=True)
        for name in ('roic_bands.csv', 'roic_bands_b2.csv', 'roic_daily_raw.csv', 'roic_daily_raw_b2.csv'):
            shutil.copyfile(OLD / name, out / name)
        for suffix, state in (('', 'a_share_daily_states_adopted.csv'), ('_b2', 'a_share_daily_states_b2.csv')):
            with (EXP / f'build_{arm}{suffix or "_base"}_bank.log').open('w') as log:
                subprocess.run([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), BANK_MODE[arm], str(out / state),
                                str(out / f'roic_daily_raw{suffix}.csv'), str(out / f'roic_bands{suffix}.csv')],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True,
                               env=dict(os.environ, PYTHONUNBUFFERED='1'))
        subprocess.run([sys.executable, str(ROOT / 'scripts/build_hold_daily_states.py'),
                        '--base', str(out / 'a_share_daily_states_adopted.csv'), '--b2', str(out / 'a_share_daily_states_b2.csv'),
                        '--out', str(out / 'a_share_daily_states_hold.csv')], cwd=ROOT, check=True)
        print('DONE', arm, flush=True)


if __name__ == '__main__':
    main()
