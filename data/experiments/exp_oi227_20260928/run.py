"""OI-227 第二步：BASE 与银行单独买入线各臂（calibrate.py 自助区间 5%／中位／95%：0.482／0.677／0.946）14 起点、全样本与剔除集 A、0bp。

状态取 v4.215 落地实验 H2 臂的面板子集（与现行生产状态逐位相同，`../exp_land_v4215_20260928/states/H2/`）；
BASE 锚点须逐字段复现在册 `summary_BASE`（面板子集等价核对）。"""
import csv
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402

STATES = ROOT / 'data/experiments/exp_land_v4215_20260928/states/H2'
ACTIONS = ROOT / 'data/experiments/exp_land_v4215_20260928/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
E1 = ['--e1-table', str(EXP / 'e1_table.csv')]
ARMS = {'BASE': [], 'BL0482': ['--bank-buy-line', '0.482'], 'BL0677': ['--bank-buy-line', '0.677'], 'BL0946': ['--bank-buy-line', '0.946']}

def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    row = next(r for r in csv.DictReader((EXP / 'cache' / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION and row['负现金日数'] == '0', tag
    return dict(arm=arm, start=start, group=group, tag=tag, **row)


def batch(group, excluded):
    jobs = [(a, s, group, excluded) for a in ARMS for s in sw.DEFAULT_STARTS]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2) as pool:
        rows = list(pool.map(one, jobs))
    with (EXP / f'sweep_{group}.txt').open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for r in rows:
            label = ('EX5:' if excluded else '') + r['arm']
            f.write('|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n")
    return rows


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades'):
        (EXP / name).mkdir(exist_ok=True)
    rows = batch('full', [])
    base = next(r for r in rows if r['arm'] == 'BASE' and r['start'] == sw.EX5_ANCHOR_START)
    with (sw.OUT_DIR / f'summary_{sw.summary_tag("BASE", sw.EX5_ANCHOR_START, "")}.csv').open() as f:
        registered = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs = {k: [registered[k], base[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if registered[k] != base[k]}
    (EXP / 'base_reproduction.json').write_text(json.dumps(dict(differences=diffs), ensure_ascii=False, indent=1) + '\n')
    assert not diffs, diffs
    A = sorted(next(r for r in rows if r['arm'] == 'BASE' and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
    rows += batch('A', A)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, arms=ARMS, A=A,
                                                          states=str(STATES), starts=sw.DEFAULT_STARTS), ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
