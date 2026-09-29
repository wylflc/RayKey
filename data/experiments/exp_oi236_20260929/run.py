"""OI-236（含 OI-235 第二轮）：参照 BTNS，NS 对照、BASE 现行；四组研究臂（preregister.md）：
G 盈利＋偏离让位细扫与分解；X 小档（加仓仍 MA20 > MA60）与让位组合；VD 持仓侧 V 回落退出；D 换仓逻辑合理化
（关闭换仓、一致的耦合换仓、解耦卖出）。14 起点、全样本与剔除集 A、0bp。

状态与公司行动同 OI-233／OI-235。BASE／NS／BTNS 全样本 14 起点须逐字段复现 OI-233 在册行，S15／X1 须复现 OI-235 在册行。
剔除集 A 同 OI-235（BTNS 锚点起点前五赢家）。每条全样本路径写闭合周期（trades/）、逐笔流水（ledgers/）、
让位流水（tlog/）与 V 回落流水（vdlog/）。

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
OI235 = ROOT / 'data/experiments/exp_oi235_20260929'
STATES = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'
ACTIONS = ROOT / 'data/experiments/exp_oi230_20260929/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
LINE = 1.0034                                  # v4.221 买入线（BASE `--width -0.0034`）
REF = 'BTNS'
A_SET = sorted('000651/601088/000338/601225/688516'.split('/'))   # OI-233 BTNS 锚点起点前五赢家（同 OI-235）
BTNS = ['--bt-quiet', '3', '--no-trend-stop']
EXT = lambda g, d: ['--swap-ext', f'{g}', f'{d}', '0']
S15 = BTNS + EXT(0.30, 0.15)
X = lambda x: ['--x', f'{x}', '--sell-x', '5.0']
VD = lambda t, m='entry': ['--vd-drop', f'{t}', '--vd-mode', m]
SELL = lambda line, gate=('20', '60'): ['--sell-line', f'{line}', '--sell-trend-ma', *gate]
SWOFF = '<no-swap>'                            # 标记：从基准命令里去掉 `--swap`
ARMS = {
    # 参照与复现
    'BASE': [], 'NS': ['--no-trend-stop'], 'BTNS': BTNS, 'S15': S15, 'X1': BTNS + X(1.0),
    # G：让位细扫（盈利 × MA20 偏离）与分解
    'G25_125': BTNS + EXT(0.25, 0.125), 'G25_15': BTNS + EXT(0.25, 0.15), 'G25_175': BTNS + EXT(0.25, 0.175),
    'G30_125': BTNS + EXT(0.30, 0.125), 'G30_175': BTNS + EXT(0.30, 0.175),
    'G40_125': BTNS + EXT(0.40, 0.125), 'G40_15': BTNS + EXT(0.40, 0.15), 'G40_175': BTNS + EXT(0.40, 0.175),
    'NOWK': BTNS + ['--swap-ext', '99', '0', '0'],
    'NSS15': ['--no-trend-stop'] + EXT(0.30, 0.15),
    # X：小档（加仓仍 MA20 > MA60）与让位组合
    'X2': BTNS + X(2.0), 'X3': BTNS + X(3.0),
    'X1S15': S15 + X(1.0), 'X2S15': S15 + X(2.0), 'X3S15': S15 + X(3.0),
    # VD：持仓侧 V 回落退出
    'VD15': BTNS + VD(0.15), 'VD20': BTNS + VD(0.20), 'VD30': BTNS + VD(0.30), 'VDP20': BTNS + VD(0.20, 'peak'),
    'VD20S15': S15 + VD(0.20),
    # D：换仓逻辑合理化
    'SWOFF': [SWOFF] + BTNS,
    'CC': BTNS + ['--swap-held-trigger', '--swap-proceeds', 'target'],
    'CCS15': S15 + ['--swap-held-trigger', '--swap-proceeds', 'target'],
    'DEC13': [SWOFF] + BTNS + SELL(1.30, ('20',)),
    'DEC13T': [SWOFF] + BTNS + SELL(1.30),
    'DEC16T': [SWOFF] + BTNS + SELL(1.60),
    'DECLT': [SWOFF] + BTNS + SELL(LINE),
    'DEXT': [SWOFF] + BTNS + ['--ext-trim', '0.30', '0.15'],
    'DEXT13T': [SWOFF] + BTNS + ['--ext-trim', '0.30', '0.15'] + SELL(1.30),
}
REPRO = {'BASE': OI233, 'NS': OI233, 'BTNS': OI233, 'S15': OI235, 'X1': OI235}
SMOKE = os.environ.get('SMOKE') == '1'
COUNTERS = ('盈利偏离·换仓让位', 'V回落·清仓', '盈利偏离·减一档', 'P/V≥估值减持线·减一档', '减持被走势闸门挡下', '换仓·减一档', '换仓·整仓卖出',
            '换仓触发·持仓不足0档', '涨幅≥110%·减一档', '诊断·持有高估日', '诊断·资金不足日', '诊断·资金不足且无未持仓候选',
            '诊断·资金不足且持有高估', '诊断·持有高估且无触发者', '超额授信·当日无新增买入')


def base_args(arm):
    base = shlex.split(sw.BASE)
    extra = list(ARMS[arm])
    if SWOFF in extra:
        extra.remove(SWOFF)
        base = [t for t in base if t != '--swap']
    return base + extra


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *base_args(arm), '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    if group == 'full':
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
    """参照臂全样本逐起点逐字段对在册行：BASE／NS／BTNS 对 OI-233，S15／X1 对 OI-235。"""
    registered = {}
    for src in set(REPRO.values()):
        for r in csv.DictReader((src / 'summary_rows.csv').open(encoding='utf-8')):
            if r['group'] == 'full' and REPRO.get(r['arm']) == src:
                registered[(r['arm'], r['start'])] = r
    diffs, checked = {}, 0
    for r in rows:
        if r['group'] != 'full' or r['arm'] not in REPRO:
            continue
        checked += 1
        reg = registered[(r['arm'], r['start'])]
        d = {k: [reg[k], r[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if reg[k] != r[k]}
        if d:
            diffs[f"{r['arm']}|{r['start']}"] = d
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=checked, fields=len(sw.FIELDS) + 1, differences=diffs),
                                                      ensure_ascii=False, indent=1) + '\n')
    assert not diffs, diffs


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades', 'ledgers', 'tlog', 'vdlog'):
        (EXP / name).mkdir(exist_ok=True)
    if SMOKE:
        rows = batch('full', [], [sw.EX5_ANCHOR_START])
        reproduce(rows)
        out = {}
        for r in rows:
            stats = json.loads((EXP / 'stats' / f"{r['tag']}.json").read_text())
            out[r['arm']] = {k: stats.get(k, 0) for k in COUNTERS if stats.get(k)}
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
