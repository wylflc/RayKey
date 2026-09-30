"""OI-241 读数第 3、6 条用：全样本 4 臂 × 14 起点重跑并落逐日持仓（股数、持仓均价、净资产），供「曾浮亏 ≥ 20% 的周期」、最大权重与具名个案。
路径与 run.py 全样本相同（同引擎、同参数、同状态），末日净资产须等于 nav/ 同路径末行。

    python3 snap.py                 # → snaps/<臂>_<起点>.csv.gz
"""
import csv
import gzip
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(EXP))
import sweep_backtest_configs as sw  # noqa: E402
from run import ACTIONS, ARMS, STATES  # noqa: E402

OUT = EXP / 'snaps'


def single(arm, start):
    from patch import load
    bt = load()
    bt.ACTIONS = Path(os.environ['EXP_ACTIONS_FILE'])
    calls = []
    original = bt.run

    def wrapped(*a, **k):
        snaps = []
        k['portfolio_snapshots'] = snaps
        result = original(*a, **k)
        calls.append((a[0] if a else k.get('strategy'), snaps, result))
        return result
    bt.run = wrapped
    tag = sw.summary_tag(arm + 'snap', start, '')
    sys.argv = ['backtest_valuation_strategy.py', *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
                '--out-dir', str(OUT / 'cache'), '--equity-bond-log-dir', str(OUT / 'daily'),
                '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    try:
        bt.main()
    except SystemExit as exc:
        assert not exc.code, exc.code
    trend = [c for c in calls if c[0] == 'trend']
    assert len(trend) == 1, [c[0] for c in calls]
    _, snaps, result = trend[0]
    with (EXP / 'nav' / f"{sw.summary_tag(arm + 'full', start, '')}.csv").open(encoding='utf-8') as f:
        last = list(csv.DictReader(f))[-1]
    end = result['equity'][-1]
    assert last['date'] == end[0] and abs(float(last['net_equity']) - end[1]) <= 1e-6 * max(1.0, end[1]), (arm, start, last, end[:2])
    equity = {d: e for d, e, *_ in result['equity']}
    with gzip.open(OUT / f'{arm}_{start}.csv.gz', 'wt', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'code', 'shares', 'cost', 'equity'])
        for s in snaps:
            for c, h in s['holdings'].items():
                w.writerow([s['date'], c, f"{h['shares']:.0f}", f"{h['cost']:.6f}", f"{equity.get(s['date'], 0):.2f}"])
    print(arm, start, len(snaps), flush=True)


def one(job):
    arm, start = job
    p = subprocess.run([sys.executable, str(EXP / 'snap.py'), '--one', arm, start], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS)))
    assert p.returncode == 0, (arm, start, p.stderr[-3000:])
    return p.stdout.strip()


def main():
    for sub in ('cache', 'daily'):
        (OUT / sub).mkdir(parents=True, exist_ok=True)
    jobs = [(a, s) for a in ARMS for s in sw.DEFAULT_STARTS]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2))) as pool:
        for line in pool.map(one, jobs):
            print(line, flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--one':
        single(sys.argv[2], sys.argv[3])
    else:
        main()
