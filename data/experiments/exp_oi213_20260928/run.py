"""OLD（现存状态）/ CONTROL / RD 及其对齐臂 同 BASE、14 起点、全／A／U、0bp。

臂集由环境变量 EXP_RUN_ARMS 给出（以 + 分隔，缺省 OLD+CONTROL+RD）；原线合格面超出 §12.1 容差的臂
另加 `<臂>_ALIGNED`，其 --width 取 align_check.json 的重解线。"""
import csv
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from common import EXP, FROZEN_ACTIONS, NIGHTLY, ROOT, digest, load, save
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw

ALIGN = load('align_check.json')['arms']
LAST_NAV = '2026-08-28'                     # 回测末次净值日（未从 summary 读到时的缺省）


def nightly_same(rel: str, end: str) -> dict:
    """冻结副本与现行文件在回测末日（含）之前的行逐行相同（忽略 *source 列的抓取日期文字）。"""
    def rows(path):
        with path.open(newline='', encoding='utf-8-sig') as f:
            return [{k: v for k, v in r.items() if 'source' not in k} for r in csv.DictReader(f) if r['observed_on'] <= end]
    old, new = rows(EXP / 'old_inputs' / rel), rows(ROOT / rel)
    return dict(rows_through_end=len(old), same_through_end=old == new)


def state_arm(arm):
    return arm.removesuffix('_ALIGNED')


def width_args(arm):
    args = shlex.split(sw.BASE)
    if arm.endswith('_ALIGNED'):
        args[args.index('--width') + 1] = f"{ALIGN[state_arm(arm)]['width']:.4f}"
    return args


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    states = EXP / 'states' / state_arm(arm)
    command = [sys.executable, str(EXP / 'engine.py'), *width_args(arm), '--since', start, '--label-suffix', '_' + tag,
               '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
               '--daily-states', str(states / 'a_share_daily_states_adopted.csv'),
               '--hold-states', str(states / 'a_share_daily_states_hold.csv')]
    if excluded:
        command += ['--exclude-codes', ','.join(excluded)]
    if group == 'full' and start == sw.EX5_ANCHOR_START:
        command += ['--trade-log', str(EXP / f'ledger_{arm}.csv'), '--candidate-log', str(EXP / f'candidates_{arm}.csv')]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f,
                           env=dict(os.environ, EXP_ACTIONS_FILE=str(FROZEN_ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    with (EXP / 'cache' / f'summary_{tag}.csv').open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION
    assert row['负现金日数'] == '0', (tag, row['负现金日数'])
    return dict(arm=arm, start=start, group=group, bp=0, tag=tag, **row)


def batch(arms, group, excluded):
    jobs = [(arm, start, group, excluded) for arm in arms for start in sw.DEFAULT_STARTS]
    print(f'START {group} {len(jobs)} paths', flush=True)
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
    print(f'DONE {group}', flush=True)
    return rows


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades'):
        (EXP / name).mkdir(exist_ok=True)
    arms = os.environ.get('EXP_RUN_ARMS', 'OLD+CONTROL+RD').replace(',', '+').split('+')   # sbatch --export 以逗号分隔变量，臂名用 +
    arms += [f'{a}_ALIGNED' for a in list(arms) if a in ALIGN and a not in ('OLD', 'CONTROL') and not ALIGN[a]['retained']]
    before = load('before_manifest.json')
    inputs = {p: digest(ROOT / p) for p in ('scripts/backtest_valuation_strategy.py', 'scripts/sweep_backtest_configs.py',
                                            'scripts/corporate_actions.py')}
    inputs |= {f'states/{a}/{n}': digest(EXP / 'states' / state_arm(a) / n) for a in arms
               for n in ('a_share_daily_states_adopted.csv', 'a_share_daily_states_hold.csv')}
    save('run_manifest.json', dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, starts=sw.DEFAULT_STARTS, arms=arms,
                                   aligned={a: ALIGN[state_arm(a)]['width'] for a in arms if a.endswith('_ALIGNED')},
                                   metric=sw.METRIC_VERSION, inputs=inputs))
    smoke = one(('OLD', sw.EX5_ANCHOR_START, 'smoke', []))
    with (EXP / 'old_inputs/data/backtest' / f'summary_BASE{sw.EX5_ANCHOR_START.replace("-", "")}.csv').open() as f:
        registered = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs = {k: [registered[k], smoke[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if registered[k] != smoke[k]}
    save('legacy_reproduction.json', dict(fields=len(sw.FIELDS) + 1, differences=diffs))
    assert not diffs, diffs
    rows = batch(arms, 'full', [])
    anchor = {a: sorted(next(r for r in rows if r['arm'] == a and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/'))
              for a in arms}
    A = anchor['OLD']
    U = sorted(set(A).union(*(set(anchor[a]) for a in arms if a not in ('OLD', 'CONTROL'))))
    save('winners.json', dict(A=A, U=U, by_arm=anchor))
    rows += batch(arms, 'A', A)
    if U != A:
        rows += batch(arms, 'U', U)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    after = {p: digest(ROOT / p) for p in before['inputs'] if p != 'frozen_actions'}
    changed = [p for p, d in after.items() if d != before['inputs'][p]]
    end = max(r['last_nav_date'] for r in rows) if rows and 'last_nav_date' in rows[0] else LAST_NAV
    audit = {p: nightly_same(p, end) for p in changed if p in NIGHTLY}
    if audit:
        save('input_change_audit.json', dict(job_id=os.getenv('SLURM_JOB_ID'), backtest_end=end, files=audit))
    changed = [p for p in changed if not audit.get(p, {}).get('same_through_end')]
    assert not changed, changed
    save('completed.json', dict(paths=len(rows) + 1, job_id=os.getenv('SLURM_JOB_ID'), unchanged_inputs=True))


if __name__ == '__main__':
    main()
