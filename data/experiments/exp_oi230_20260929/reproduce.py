"""安装前核对：v4.221 代码以生产模式 `h2:0.02:0.10`（缺省可持续终值、k = BANK_SCALE）在冻结输入上重跑两侧银行覆盖，
须与候选检验的 DC 臂（研究开关 `h2:0.02:0.10:0.7045:sus`）逐字节相同；否则中止安装。"""
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import EXP, ROOT, digest, save


def one(side: str) -> dict:
    suffix, state = ('', 'a_share_daily_states_adopted.csv') if side == 'base' else ('_b2', 'a_share_daily_states_b2.csv')
    build = EXP / 'states/DC_build'
    out = Path(tempfile.mkdtemp(prefix='oi230_repro_', dir=os.environ.get('TMPDIR'))) / state
    subprocess.run([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), 'h2:0.02:0.10', str(out),
                    str(build / f'roic_daily_raw{suffix}.csv'), str(build / f'roic_bands{suffix}.csv')],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    got, want = digest(out), digest(build / state)
    out.unlink()
    return dict(side=side, production_mode=got, dc_arm=want, identical=got == want)


def main():
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(one, ('base', 'b2')))
    save('reproduction.json', dict(job_id=os.getenv('SLURM_JOB_ID'), sides=result))
    print(result, flush=True)
    assert all(r['identical'] for r in result), 'production mode does not reproduce the DC arm'


if __name__ == '__main__':
    main()
