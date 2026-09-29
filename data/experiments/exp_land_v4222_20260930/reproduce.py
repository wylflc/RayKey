"""v4.222 落地核对：原生引擎（`--bt-quiet`／`--swap-ext` 已移入）在在册 BASE 上逐字段复现 OI-237 的 BASE 行，
BASE ＋ `--bt-quiet 3 --no-trend-stop --swap-ext 0.3 0.15 0` 逐字段复现 OI-237 的 S15 行；14 起点 × 全样本、A、UC，48 字段 ＋ 同窗序列。

    python3 reproduce.py
"""
import csv, json, os, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
OI237 = ROOT / 'data/experiments/exp_oi237_20260930'
STATES = ROOT / 'data/experiments/exp_oi230_20260929/states/DC'
ACTIONS = ROOT / 'data/experiments/exp_oi230_20260929/old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
OLD_BASE = os.environ.get('OLD_BASE', sw.BASE)            # 移入前的在册 BASE（sweep_backtest_configs 改写后由环境变量传入）
ARMS = {'BASE': [], 'S15': ['--bt-quiet', '3', '--no-trend-stop', '--swap-ext', '0.3', '0.15', '0']}
GROUPS = {'full': [], 'A': sorted('000651/002128/600066/601088/688516'.split('/')),
          'UC': sorted('000338/000651/002128/600066/600897/601088/601225/688516'.split('/'))}
OUT = EXP / 'native'


def one(job):
    arm, start, group = job
    ex = GROUPS[group]
    tag = sw.summary_tag(arm + group, start, ','.join(ex))
    cmd = [sys.executable, str(EXP / 'native_engine.py'), *shlex.split(OLD_BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(OUT / 'cache'), '--equity-bond-log-dir', str(OUT / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if ex:
        cmd += ['--exclude-codes', ','.join(ex)]
    with (OUT / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    return dict(arm=arm, start=start, group=group, **next(r for r in csv.DictReader((OUT / 'cache' / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_')))


def main():
    for name in ('cache', 'daily', 'errors'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    reg = {(r['arm'], r['group'], r['start']): r for r in csv.DictReader((OI237 / 'summary_rows.csv').open(encoding='utf-8'))
           if r['arm'] in ARMS and r['group'] in GROUPS}
    jobs = [(a, s, g) for a in ARMS for s in sw.DEFAULT_STARTS for g in GROUPS]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', 14))) as pool:
        rows = list(pool.map(one, jobs))
    diffs = {}
    for r in rows:
        old = reg[(r['arm'], r['group'], r['start'])]
        d = {k: [old[k], r[k]] for k in (*sw.FIELDS, sw.WIN5_KEY) if old[k] != r[k]}
        if d:
            diffs[f"{r['arm']}|{r['group']}|{r['start']}"] = d
    (EXP / 'reproduction.json').write_text(json.dumps(dict(paths=len(rows), fields=len(sw.FIELDS) + 1, base=OLD_BASE, differences=diffs),
                                                      ensure_ascii=False, indent=1) + '\n')
    print(len(rows), 'paths;', len(diffs), 'with differences')
    assert not diffs


if __name__ == '__main__':
    main()
