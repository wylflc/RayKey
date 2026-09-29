"""OI-237：BTNS 与让位换仓的组合确认（preregister.md）。参照 BASE；26 臂 × 14 起点；全样本、剔除集 A、逐臂 U、共同剔除集 UC；0bp。

状态与公司行动同 OI-233／OI-235／OI-236；引擎为 OI-236 补丁，不加新开关。全样本路径写闭合周期（trades/）、逐笔流水（ledgers/）
与让位流水（tlog/）。复现：BASE／NS／BTNS 的全样本与 A 对 OI-233 在册行，S15／G25_15／G25_175／G30_175／X3S15／CCS15／NSS15
的全样本对 OI-236 在册行，逐起点逐字段相同。A = OI-233 BASE 锚点前五；U = A ∪ 该臂锚点前五（BASE 按每个不同的 U 重跑）；
UC = A ∪ S15 格 2×2 四臂锚点前五，全部臂重跑。

    python3 run.py
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
OI236 = ROOT / 'data/experiments/exp_oi236_20260929'
STATES = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'
ACTIONS = ROOT / 'data/experiments/exp_oi230_20260929/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
LINE = 1.0034                                  # v4.221 买入线（BASE `--width -0.0034`）
REF = 'BASE'
A_SET = sorted('000651/002128/600066/601088/688516'.split('/'))   # OI-233 BASE 锚点起点前五赢家
UC_FROM = ('S15', 'X3S15', 'CCS15', 'X3CCS15')                    # 共同剔除集 UC = A ∪ 这四臂锚点前五
NS = ['--no-trend-stop']
BTNS = ['--bt-quiet', '3'] + NS
EXT = lambda g, d: ['--swap-ext', f'{g}', f'{d}', '0']
X = lambda x: ['--x', f'{x}', '--sell-x', '5.0']
CC = ['--swap-held-trigger', '--swap-proceeds', 'target']
CELLS = {'S15': (0.30, 0.15), 'G25_15': (0.25, 0.15), 'G25_175': (0.25, 0.175), 'G30_175': (0.30, 0.175)}
VARIANTS = (('', []), ('X3', X(3.0)), ('CC', CC), ('X3CC', X(3.0) + CC))    # 5%·S、3%·S、5%·CC、3%·CC
ARMS = {'BASE': [], 'NS': NS, 'BTNS': BTNS, 'BS15': EXT(0.30, 0.15)}
for _pre, _extra in VARIANTS:
    for _cell, (_g, _d) in CELLS.items():
        ARMS[_pre + _cell] = BTNS + EXT(_g, _d) + _extra
ARMS.update({'X4S15': BTNS + EXT(0.30, 0.15) + X(4.0), 'X4CCS15': BTNS + EXT(0.30, 0.15) + X(4.0) + CC})
for _pre, _extra in VARIANTS:
    ARMS['NS' + _pre + 'S15'] = NS + EXT(0.30, 0.15) + _extra
REPRO = {'BASE': OI233, 'NS': OI233, 'BTNS': OI233, **{a: OI236 for a in ('S15', 'G25_15', 'G25_175', 'G30_175', 'X3S15', 'CCS15', 'NSS15')}}
REPRO_A = ('BASE', 'NS', 'BTNS')               # 剔除集 A 与 OI-233 相同，这三臂的 A 行也对在册行


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
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


def run_jobs(jobs):
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2))) as pool:
        return list(pool.map(one, jobs))


def write_sweep(path, rows, excluded=None):
    with path.open('w') as f:
        f.write(sw.metric_header() + '\n#MARKET|a\n')
        if excluded:
            f.write('#EX5|fixed|' + ','.join(excluded) + '\n')
        for r in rows:
            label = ('EX5:' if excluded else '') + r['arm']
            f.write('|'.join([label, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n')
            f.write(f"#WIN5|{label}|{r['start']}|{r[sw.WIN5_KEY]}\n")


def reproduce(rows):
    """全样本：BASE／NS／BTNS 对 OI-233、让位五臂与 NSS15 对 OI-236；剔除集 A：BASE／NS／BTNS 对 OI-233。逐起点逐字段。"""
    registered = {}
    for src in (OI233, OI236):
        for r in csv.DictReader((src / 'summary_rows.csv').open(encoding='utf-8')):
            if (r['group'] == 'full' and REPRO.get(r['arm']) == src) or (r['group'] == 'A' and src == OI233 and r['arm'] in REPRO_A):
                registered[(r['arm'], r['group'], r['start'])] = r
    diffs, checked = {}, 0
    for r in rows:
        reg = registered.get((r['arm'], r['group'], r['start']))
        if reg is None:
            continue
        checked += 1
        d = {k: [reg[k], r[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if reg[k] != r[k]}
        if d:
            diffs[f"{r['arm']}|{r['group']}|{r['start']}"] = d
    return checked, diffs


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades', 'ledgers', 'tlog', 'u'):
        (EXP / name).mkdir(exist_ok=True)
    full = run_jobs([(a, s, 'full', []) for a in ARMS for s in sw.DEFAULT_STARTS])
    checked, diffs = reproduce(full)
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=checked, fields=len(sw.FIELDS) + 1, differences=diffs),
                                                      ensure_ascii=False, indent=1) + '\n')
    assert not diffs, diffs
    top5 = {r['arm']: [c for c in r[sw.EX5_FIELD].split('/') if c] for r in full if r['start'] == sw.EX5_ANCHOR_START}
    u_sets = {a: sorted(set(A_SET) | set(top5[a])) for a in ARMS if a != REF}
    u_id = {u: f'U{i:02d}' for i, u in enumerate(sorted({tuple(u) for u in u_sets.values()}), 1)}
    uc = sorted(set(A_SET).union(*(top5[a] for a in UC_FROM)))
    rest = run_jobs([(a, s, 'A', A_SET) for a in ARMS for s in sw.DEFAULT_STARTS]
                    + [(a, s, 'U', u_sets[a]) for a in u_sets for s in sw.DEFAULT_STARTS]
                    + [(REF, s, gid, list(u)) for u, gid in u_id.items() for s in sw.DEFAULT_STARTS]
                    + [(a, s, 'UC', uc) for a in ARMS for s in sw.DEFAULT_STARTS])
    checked_a, diffs_a = reproduce(rest)
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=checked + checked_a, fields=len(sw.FIELDS) + 1, differences={**diffs, **diffs_a}),
                                                      ensure_ascii=False, indent=1) + '\n')
    rows = full + rest
    write_sweep(EXP / 'sweep_full.txt', full)
    write_sweep(EXP / 'sweep_A.txt', [r for r in rest if r['group'] == 'A'], A_SET)
    write_sweep(EXP / 'sweep_UC.txt', [r for r in rest if r['group'] == 'UC'], uc)
    for a, u in u_sets.items():
        gid = u_id[tuple(u)]
        pair = [r for r in rest if (r['arm'] == a and r['group'] == 'U') or (r['arm'] == REF and r['group'] == gid)]
        write_sweep(EXP / 'u' / f'{a}.txt', pair, u)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, ref=REF, arms=ARMS, A=A_SET,
                                                          top5=top5, U=u_sets, U_groups={g: list(u) for u, g in u_id.items()}, UC=uc,
                                                          UC_from=UC_FROM, states=str(STATES.relative_to(ROOT)),
                                                          actions=str(ACTIONS.relative_to(ROOT)), starts=sw.DEFAULT_STARTS),
                                                     ensure_ascii=False, indent=1) + '\n')
    assert not diffs_a, diffs_a


if __name__ == '__main__':
    main()
