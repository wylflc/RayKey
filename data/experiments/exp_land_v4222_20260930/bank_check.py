"""v4.222 落地前核对（用户 2026-09-30 问：今天的回测按哪种银行估值算；若银行仍按旧法，结果会不会变）：
今天 OI-233～OI-240 全部用 v4.221 状态（OI-230 `DC` 臂，新银行 DDM）。本脚本在 OI-230 `CONTROL` 状态（v4.220 旧银行口径）上
重跑 BASE 与 S15（14 起点、全样本与剔除集 A = CONTROL 下 BASE 锚点前五），CONTROL 下 BASE 全样本须逐字段复现 OI-230 在册行，
再比较 S15 对 BASE 的读数在两套银行口径下是否一致。

    python3 bank_check.py
"""
import csv, json, os, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw  # noqa: E402
OI230 = ROOT / 'data/experiments/exp_oi230_20260929'
OI237 = ROOT / 'data/experiments/exp_oi237_20260930'
ACTIONS = OI230 / 'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
STATES = OI230 / 'states/CONTROL'
A_SET = sorted('000651/002128/601088/601225/688516'.split('/'))        # OI-230 CONTROL 下 BASE 锚点前五
ARMS = {'BASE': [], 'S15': ['--bt-quiet', '3', '--no-trend-stop', '--swap-ext', '0.3', '0.15', '0']}
OUT = EXP / 'bank_check'


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    cmd = [sys.executable, str(OI237 / 'engine.py'), *shlex.split(sw.BASE), *ARMS[arm], '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(OUT / 'cache'), '--equity-bond-log-dir', str(OUT / 'daily'),
           '--daily-states', str(STATES / 'a_share_daily_states_adopted.csv'), '--hold-states', str(STATES / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    with (OUT / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=dict(os.environ, EXP_ACTIONS_FILE=str(ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    row = next(r for r in csv.DictReader((OUT / 'cache' / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))
    assert row['计量版本'] == sw.METRIC_VERSION and row['负现金日数'] == '0', tag
    return dict(arm=arm, start=start, group=group, tag=tag, **row)


def main():
    for name in ('cache', 'daily', 'errors'):
        (OUT / name).mkdir(parents=True, exist_ok=True)
    jobs = [(a, s, g, ex) for a in ARMS for s in sw.DEFAULT_STARTS for g, ex in (('full', []), ('A', A_SET))]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('WORKERS', 14))) as pool:
        rows = list(pool.map(one, jobs))
    reg = {r['start']: r for r in csv.DictReader((OI230 / 'summary_rows.csv').open(encoding='utf-8')) if r['arm'] == 'CONTROL' and r['group'] == 'full'}
    diffs = {r['start']: {k: [reg[r['start']][k], r[k]] for k in sw.FIELDS if reg[r['start']][k] != r[k]}
             for r in rows if r['arm'] == 'BASE' and r['group'] == 'full'}
    diffs = {k: v for k, v in diffs.items() if v}
    for g, ex in (('full', None), ('A', A_SET)):
        with (OUT / f'sweep_{g}.txt').open('w') as f:
            f.write(sw.metric_header() + '\n#MARKET|a\n' + (('#EX5|fixed|' + ','.join(ex) + '\n') if ex else ''))
            for r in rows:
                if r['group'] != g:
                    continue
                lab = ('EX5:' if ex else '') + r['arm']
                f.write('|'.join([lab, r['start']] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n')
                f.write(f"#WIN5|{lab}|{r['start']}|{r[sw.WIN5_KEY]}\n")
    def load(p):
        sw.set_market(sw.scan_market(p)); g, *_ = sw.load_scan(p); return g
    F, A = load(OUT / 'sweep_full.txt')[''], load(OUT / 'sweep_A.txt')[sw.EX5_PREFIX]
    pm = lambda g, k: sw._paired_median(g, 'S15', k, ref='BASE')
    res = dict(states=str(STATES.relative_to(ROOT)), A=A_SET, base_reproduces_oi230_control=not diffs, diffs=diffs,
               control=dict(flag=sw.reading_flags(F, A, 'S15')[0], main=[pm(F, sw.WIN5_KEY), pm(A, sw.WIN5_KEY)], cagr=[pm(F, '年化'), pm(A, '年化')],
                            mdd=pm(F, '最大回撤'), wins=sum(F['S15'][s]['年化'] > F['BASE'][s]['年化'] for s in sw.DEFAULT_STARTS),
                            base_cagr=sorted(F['BASE'][s]['年化'] for s in sw.DEFAULT_STARTS)[7], s15_cagr=sorted(F['S15'][s]['年化'] for s in sw.DEFAULT_STARTS)[7]))
    (EXP / 'bank_check.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')
    print(json.dumps(res, ensure_ascii=False, default=float)[:1500])


if __name__ == '__main__':
    main()
