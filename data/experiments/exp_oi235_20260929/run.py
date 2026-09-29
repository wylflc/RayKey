"""OI-235：以 BTNS（OI-233 前低企稳建仓＋不止损）为参照，NS 为对照、BASE 为现行生产，跑三组研究臂（preregister.md）：
A 加仓同建仓条件＋一档改小；B 换仓源改为盈利＋偏离、做 T 买回；C 买入线以上卖出。14 起点、全样本与剔除集 A、0bp。

状态取 v4.221 落地所用 OI-230 DC 臂的面板子集与其冻结公司行动（与 OI-233 同）。BASE／NS／BTNS 全样本 14 起点须逐字段
复现 OI-233 在册 `summary_rows.csv`（补丁叠加、开关关闭时的等价核对）。剔除集 A = 参照臂 BTNS 锚点起点前五赢家
（OI-233 在册）。每条全样本路径写闭合周期（trades/）与让位／买回流水（tlog/）。

    python3 run.py            # 全量
    SMOKE=1 python3 run.py    # 只跑锚点起点全样本：复现核对与各开关触发计数（smoke.json）
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

OI233 = ROOT / 'data/experiments/exp_oi233_20260929'
STATES = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'
ACTIONS = ROOT / 'data/experiments/exp_oi230_20260929/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
LINE = 1.0034                                  # v4.221 买入线（BASE `--width -0.0034`）
REF = 'BTNS'
A_SET = sorted('000651/601088/000338/601225/688516'.split('/'))   # OI-233 BTNS 锚点起点前五赢家
BTNS = ['--bt-quiet', '3', '--no-trend-stop']
S15 = BTNS + ['--swap-ext', '0.30', '0.15', '0']
ARMS = {
    'BASE': [],
    'NS': ['--no-trend-stop'],
    'BTNS': BTNS,
    'A1': BTNS + ['--add-bt', '--x', '1.0', '--sell-x', '5.0'],
    'A2': BTNS + ['--add-bt', '--x', '2.0', '--sell-x', '5.0'],
    'A5': BTNS + ['--add-bt'],
    'X1': BTNS + ['--x', '1.0', '--sell-x', '5.0'],
    'S10': BTNS + ['--swap-ext', '0.20', '0.10', '0'],
    'S15': S15,
    'S20': BTNS + ['--swap-ext', '0.50', '0.20', '0'],
    'E5': BTNS + ['--swap-ext', '0.30', '0', '0.05'],
    'S15T5': S15 + ['--swap-bb', '5', '0.05'],
    'S15T20': S15 + ['--swap-bb', '20', '0.05'],
    'S15T20b': S15 + ['--swap-bb', '20', '0.10'],
    'V': BTNS + ['--sell-line', f'{LINE}', '--value-sell-ungated'],
    'VF': BTNS + ['--sell-line', f'{LINE}', '--value-sell-ungated', '--value-sell-full'],
}
REPRO = ('BASE', 'NS', 'BTNS')
SMOKE = os.environ.get('SMOKE') == '1'
COUNTERS = ('前低建仓', '盈利偏离·换仓让位', '做T·买回', 'P/V≥估值减持线·减一档', 'P/V过线·整仓卖出', '换仓·减一档', '换仓·整仓卖出',
            '涨幅≥110%·减一档', '买不足一手·跳过', '超额授信·当日无新增买入')


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    if group == 'full':                        # 逐笔流水：读数 1 的机会段成本加权均价要全部全样本路径的每笔买入
        cmd += ['--trade-log', str(EXP / 'ledgers' / (f'ledger_{arm}.csv' if start == sw.EX5_ANCHOR_START else f'{tag}.csv'))]
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
    """BASE／NS／BTNS 全样本逐起点逐字段对 OI-233 在册行。"""
    registered = {(r['arm'], r['start']): r for r in csv.DictReader((OI233 / 'summary_rows.csv').open(encoding='utf-8')) if r['group'] == 'full'}
    diffs = {}
    for r in rows:
        if r['group'] != 'full' or r['arm'] not in REPRO:
            continue
        reg = registered[(r['arm'], r['start'])]
        d = {k: [reg[k], r[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if reg[k] != r[k]}
        if d:
            diffs[f"{r['arm']}|{r['start']}"] = d
    checked = sum(1 for r in rows if r['group'] == 'full' and r['arm'] in REPRO)
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=checked, fields=len(sw.FIELDS) + 1, differences=diffs),
                                                      ensure_ascii=False, indent=1) + '\n')
    assert not diffs, diffs


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades', 'ledgers', 'tlog'):
        (EXP / name).mkdir(exist_ok=True)
    if SMOKE:
        rows = batch('full', [], [sw.EX5_ANCHOR_START])
        reproduce(rows)
        out = {}
        for r in rows:
            stats = json.loads((EXP / 'stats' / f"{r['tag']}.json").read_text())
            out[r['arm']] = {k: stats.get(k, 0) for k in COUNTERS}
        (EXP / 'smoke.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), reproduced=list(REPRO), arms=out),
                                                   ensure_ascii=False, indent=1) + '\n')
        print(json.dumps(out, ensure_ascii=False))
        return
    rows = batch('full', [])
    reproduce(rows)
    rows += batch('A', A_SET)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, ref=REF, arms=ARMS, A=A_SET,
                                                          states=str(STATES.relative_to(ROOT)), actions=str(ACTIONS.relative_to(ROOT)),
                                                          starts=sw.DEFAULT_STARTS), ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
