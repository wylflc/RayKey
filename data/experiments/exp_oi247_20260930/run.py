"""OI-247：现行策略的止损两方案（preregister.md）。
18 臂 × 14 起点：S15（参照，即现行 BASE）；方案一 SA20L／SA60L／SA20C／SA60C（前低止损、走强解除）与分解对照 SP20L（不解除）；
方案二 LT{63,126,189,252}K{5,10,15}（长期水下减仓）。全样本、剔除集 A（S15 锚点前五）、逐新臂 U；0bp。

状态与公司行动同 v4.225 在册 BASE（现行正式文件）；引擎 = 原生引擎 ＋ 本目录 patch.py（开关全关时逐位相同）。
复现：S15 全样本 14 条路径须对 `exp_land_v4225_20260930` 在册 NEW 行逐字段相同，锚点前五须等于 A。

    python3 run.py
    python3 run.py --smoke      # 冒烟：2011-11-01 起点，S15、SA20L、SP20L、LT126K10 各一条
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

REGISTERED = ROOT / 'data/experiments/exp_land_v4225_20260930/summary_rows.csv'
STATES = ROOT / 'data/processed'
LINE = 1.0034
REF = 'S15'
A_SET = sorted('000651/601088/000338/601225/600897'.split('/'))      # S15 锚点前五（v4.225 在册 A）
SA = {'SA20L': (20, 'low'), 'SA60L': (60, 'low'), 'SA20C': (20, 'close'), 'SA60C': (60, 'close')}
ARMS = {REF: []}
for _k, (_w, _c) in SA.items():
    ARMS[_k] = ['--bt-stop-window', str(_w), '--bt-stop-col', _c, '--bt-stop-release', '--bt-no-anchor-nostop']
ARMS['SP20L'] = ['--bt-no-anchor-nostop']
LT = {}
for _m in (63, 126, 189, 252):
    for _x in (5, 10, 15):
        LT[f'LT{_m}K{_x}'] = (_m, _x / 100)
        ARMS[f'LT{_m}K{_x}'] = ['--loss-age-days', str(_m), '--loss-age-keep', f'{_x / 100:g}']
STOP_ARMS = set(SA) | {'SP20L'}                                        # 这些臂去掉 BASE 的 --no-trend-stop
NEW = [a for a in ARMS if a != REF]


def base_tokens(arm):
    tokens = shlex.split(sw.BASE)
    if arm in STOP_ARMS:
        assert tokens.count('--no-trend-stop') == 1
        tokens.remove('--no-trend-stop')
    return tokens


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(EXP / 'engine.py'), *base_tokens(arm), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    if group == 'full':
        cmd += ['--trade-log', str(EXP / 'ledgers' / (f'ledger_{arm}.csv' if start == sw.EX5_ANCHOR_START else f'{tag}.csv'))]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f)
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
    """S15 全样本对 v4.225 在册 NEW 行逐起点逐字段。"""
    registered = {r['start']: r for r in csv.DictReader(REGISTERED.open(encoding='utf-8')) if r['arm'] == 'NEW' and r['group'] == 'full'}
    diffs, checked = {}, 0
    for r in rows:
        if r['arm'] != REF or r['group'] != 'full' or r['start'] not in registered:
            continue
        reg = registered[r['start']]
        checked += 1
        d = {k: [reg[k], r[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if reg[k] != r[k]}
        if d:
            diffs[r['start']] = d
    return checked, diffs


def dirs():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades', 'ledgers', 'snaps', 'u'):
        (EXP / name).mkdir(exist_ok=True)


def smoke():
    dirs()
    rows = run_jobs([(a, sw.EX5_ANCHOR_START, 'full', []) for a in (REF, 'SA20L', 'SP20L', 'LT126K10')])
    checked, diffs = reproduce(rows)
    out = dict(reproduction=dict(paths=checked, differences=diffs),
               rows={r['arm']: {k: r[k] for k in ('年化', '最大回撤', sw.EX5_FIELD)} for r in rows},
               stats={r['arm']: {k: v for k, v in json.loads((EXP / 'stats' / f"{r['tag']}.json").read_text()).items()
                                 if any(s in k for s in ('前低', '止损', '水下'))} for r in rows})
    (EXP / 'smoke.json').write_text(json.dumps(out, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(out, ensure_ascii=False, indent=1))
    assert not diffs, diffs


def main():
    dirs()
    full = run_jobs([(a, s, 'full', []) for a in ARMS for s in sw.DEFAULT_STARTS])
    checked, diffs = reproduce(full)
    top5 = {r['arm']: [c for c in r[sw.EX5_FIELD].split('/') if c] for r in full if r['start'] == sw.EX5_ANCHOR_START}
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=checked, fields=len(sw.FIELDS) + 1, differences=diffs,
                                                           ref_top5=top5[REF], A=A_SET), ensure_ascii=False, indent=1) + '\n')
    assert checked == len(sw.DEFAULT_STARTS) and not diffs, (checked, diffs)
    assert sorted(top5[REF]) == A_SET, (top5[REF], A_SET)
    u_sets = {a: sorted(set(A_SET) | set(top5[a])) for a in NEW}
    u_id = {u: f'U{i:02d}' for i, u in enumerate(sorted({tuple(u) for u in u_sets.values()}), 1)}
    rest = run_jobs([(a, s, 'A', A_SET) for a in ARMS for s in sw.DEFAULT_STARTS]
                    + [(a, s, 'U', u_sets[a]) for a in NEW for s in sw.DEFAULT_STARTS]
                    + [(REF, s, gid, list(u)) for u, gid in u_id.items() for s in sw.DEFAULT_STARTS])
    rows = full + rest
    write_sweep(EXP / 'sweep_full.txt', full)
    write_sweep(EXP / 'sweep_A.txt', [r for r in rest if r['group'] == 'A'], A_SET)
    for a, u in u_sets.items():
        gid = u_id[tuple(u)]
        write_sweep(EXP / 'u' / f'{a}.txt', [r for r in rest if (r['arm'] == a and r['group'] == 'U') or (r['arm'] == REF and r['group'] == gid)], u)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, ref=REF, arms=ARMS,
                                                          stop_arms=sorted(STOP_ARMS), A=A_SET, top5=top5, U=u_sets,
                                                          U_groups={g: list(u) for u, g in u_id.items()},
                                                          states=str(STATES.relative_to(ROOT)), starts=sw.DEFAULT_STARTS),
                                                     ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    smoke() if '--smoke' in sys.argv else main()
