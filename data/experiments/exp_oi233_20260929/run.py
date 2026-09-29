"""OI-233：BASE 与 ZH（区内不做价格止损）、NS（不做价格止损，用户方案一）、BT（前低企稳＋站上 MA5／MA20 建仓、
破前低清仓，用户方案二）各臂 14 起点、全样本与剔除集 A、0bp（preregister.md）。

状态取 v4.221 落地所用 OI-230 DC 臂的面板子集（`../exp_oi230_20260929/states/DC/`）与其冻结公司行动；
BASE 锚点须逐字段复现在册 `summary_BASE20111101.csv`（面板子集与补丁关闭时的等价核对）。
剔除集 A = 本批 BASE 臂锚点起点前五赢家。每条全样本路径写闭合周期（trades/），供第 13 款与执行读数。

    python3 run.py            # 全量
    SMOKE=1 python3 run.py    # 只跑锚点起点全样本：BASE 复现核对与各开关触发计数（smoke.json）
"""
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

STATES = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'
ACTIONS = ROOT / 'data/experiments/exp_oi230_20260929/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
LINE = 1.0034                                  # v4.221 买入线（BASE `--width -0.0034`）
ARMS = {
    'BASE': [],
    'ZH070': ['--zone-hold-pv', '0.70'],
    'ZH085': ['--zone-hold-pv', '0.85'],
    'ZHL': ['--zone-hold-pv', f'{LINE}'],
    'NS': ['--no-trend-stop'],
    'BT2': ['--bt-quiet', '2'],
    'BT3': ['--bt-quiet', '3'],
    'BT5': ['--bt-quiet', '5'],
    'BTNS': ['--bt-quiet', '3', '--no-trend-stop'],
}
SMOKE = os.environ.get('SMOKE') == '1'


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    if group == 'full' and start == sw.EX5_ANCHOR_START:
        cmd += ['--trade-log', str(EXP / 'ledgers' / f'ledger_{arm}.csv')]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    row = next(r for r in csv.DictReader((EXP / 'cache' / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION and row['负现金日数'] == '0', tag
    return dict(arm=arm, start=start, group=group, tag=tag, **row)


def batch(group, excluded, starts=None):
    jobs = [(a, s, group, excluded) for a in ARMS for s in (starts or sw.DEFAULT_STARTS)]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2))) as pool:
        rows = list(pool.map(one, jobs))
    if starts:
        return rows
    with (EXP / f'sweep_{group}.txt').open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for r in rows:
            label = ('EX5:' if excluded else '') + r['arm']
            f.write('|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n")
    return rows


def reproduce(rows):
    base = next(r for r in rows if r['arm'] == 'BASE' and r['start'] == sw.EX5_ANCHOR_START)
    with (sw.OUT_DIR / f'summary_{sw.summary_tag("BASE", sw.EX5_ANCHOR_START, "")}.csv').open() as f:
        registered = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    diffs = {k: [registered[k], base[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if registered[k] != base[k]}
    (EXP / 'base_reproduction.json').write_text(json.dumps(dict(fields=len(sw.FIELDS) + 1, differences=diffs), ensure_ascii=False, indent=1) + '\n')
    assert not diffs, diffs
    return base


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades', 'ledgers'):
        (EXP / name).mkdir(exist_ok=True)
    if SMOKE:
        rows = batch('full', [], [sw.EX5_ANCHOR_START])
        reproduce(rows)
        keys = ('止损·区内暂停（日）', '前低建仓', '前低建仓·无锚沿用MA60')
        out = {}
        for r in rows:
            stats = json.loads((EXP / 'stats' / f"{r['tag']}.json").read_text())
            reasons = {}
            with (EXP / 'ledgers' / f"ledger_{r['arm']}.csv").open(newline='', encoding='utf-8') as f:
                for x in csv.DictReader(f):
                    why = x.get('reason') or ''
                    for s in ('止损', '移出股票库', '换仓', '涨幅', '股债', '强平'):
                        if s in why:
                            reasons[s] = reasons.get(s, 0) + 1
            out[r['arm']] = dict(counters={k: stats.get(k, 0) for k in keys}, ledger_reasons=reasons)
        (EXP / 'smoke.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base_reproduced=True, arms=out),
                                                   ensure_ascii=False, indent=1) + '\n')
        print(json.dumps(out, ensure_ascii=False))
        return
    rows = batch('full', [])
    base = reproduce(rows)
    A = sorted(base['前五赢家'].split('/'))
    rows += batch('A', A)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, arms=ARMS, A=A,
                                                          states=str(STATES.relative_to(ROOT)), actions=str(ACTIONS.relative_to(ROOT)),
                                                          starts=sw.DEFAULT_STARTS), ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
