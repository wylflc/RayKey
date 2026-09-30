"""两臂（S15 = 现行 BASE，OLD = v4.221 BASE）× 14 个标准起点，长跑到 09-29。

    WORKERS=16 python3 run.py
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from common import EXP, ROOT
import sweep_backtest_configs as sw

JOBS = [(arm, start) for arm in ('S15', 'OLD') for start in sw.DEFAULT_STARTS]


def one(job):
    arm, start = job
    (EXP / 'runs').mkdir(exist_ok=True)
    with (EXP / 'runs' / f'{arm}_{start}.log').open('w') as log:
        p = subprocess.run([sys.executable, str(EXP / 'run_one.py'), arm, start], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1'))
    return arm, start, p.returncode


def main():
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', 16))) as pool:
        done = list(pool.map(one, JOBS))
    bad = [d for d in done if d[2]]
    print(len(done), 'runs;', 'failed', bad, flush=True)
    assert not bad


if __name__ == '__main__':
    main()
