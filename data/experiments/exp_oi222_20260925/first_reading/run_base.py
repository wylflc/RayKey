"""OI-222 第一份读数：现行 BASE 在 14 个标准起点上带逐周期产物重跑，并逐起点核对与在册 summary 一致（§12.1 第 1 款）。

    python3 run_base.py      # → bt/<起点>/*_trades.csv、reproduction.json
"""
import csv
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402

KEYS = ('年化', '最大回撤', '滚动5年年化中位', '期末净资产')


def run(start: str) -> dict:
    tag = sw.summary_tag('BASE', start, '')
    out = HERE / 'bt' / start
    out.mkdir(parents=True, exist_ok=True)
    cmd = ([sys.executable, str(ROOT / 'scripts/backtest_valuation_strategy.py')] + shlex.split(sw.BASE)
           + ['--since', start, '--label-suffix', '_' + tag, '--out-dir', str(out), '--artifacts'])
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (out / 'run.log').write_text(done.stdout[-20000:] + '\n--- stderr ---\n' + done.stderr[-20000:])
    new = [r for r in csv.DictReader((out / f'summary_{tag}.csv').open(encoding='utf-8')) if r['策略'].startswith('trend_')][-1]
    old = next(csv.DictReader((sw.OUT_DIR / f'summary_{tag}.csv').open(encoding='utf-8')))
    same = {k: new.get(k) == old.get(k) for k in KEYS if k in old}
    return dict(start=start, returncode=done.returncode, reproduced=all(same.values()), fields=same,
                annualized=float(new['年化']), trades=[p.name for p in out.glob('*_trades.csv')])


def main():
    workers = min(len(sw.DEFAULT_STARTS), int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(run, sw.DEFAULT_STARTS))
    (HERE / 'reproduction.json').write_text(json.dumps(results, ensure_ascii=False, indent=1) + '\n')
    bad = [r['start'] for r in results if r['returncode'] or not r['reproduced'] or len(r['trades']) != 1]
    print('reproduced', sum(r['reproduced'] for r in results), '/', len(results), 'bad', bad)
    if bad:
        raise SystemExit(f'BASE 重跑与在册读数不一致或缺逐周期产物：{bad}')


if __name__ == '__main__':
    main()
