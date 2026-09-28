"""OI-207 H2 落地检验：BASE（生产状态）与 H2（银行行改写）14 起点、全样本／A／U、0bp，随后出读数。

    python3 run.py        # → summary_rows.csv、sweep_*.txt、report_H2_*.txt、opportunity_trap.md、case_attribution.md、current_banks.json
"""
import contextlib
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

ENGINE = ROOT / 'data/experiments/exp_oi224_exec_20260928/engine.py'   # 同一包装：逐路径写净值、全样本写闭合周期
ARMS = ('BASE', 'H2')


def one(job):
    arm, start, group, excluded = job
    tag = sw.summary_tag(arm + group, start, ','.join(excluded))
    states = EXP / 'states' / arm
    cmd = [sys.executable, str(ENGINE), *shlex.split(sw.BASE), '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'cache'), '--equity-bond-log-dir', str(EXP / 'daily'),
           '--daily-states', str(states / 'a_share_daily_states_adopted.csv'), '--hold-states', str(states / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f,
                           env=dict(os.environ, EXP_ACTIONS_FILE=str(ROOT / 'data/raw/corporate_actions/a_share_corporate_actions.csv')))
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


def readings(A, U):
    for group in ('A',) + (('U',) if U != A else ()):
        text = []
        for g in ('full', group):
            for ln in (EXP / f'sweep_{g}.txt').read_text().splitlines()[(0 if g == 'full' else 2):]:
                text.append(ln)
        combined = EXP / f'sweep_H2_full_{group}.txt'
        combined.write_text('\n'.join(text) + '\n')
        with (EXP / f'report_H2_full_{group}.txt').open('w') as f, contextlib.redirect_stdout(f):
            sw.report(combined, f'OI-207 H2 vs BASE（v4.213 状态、0bp）｜剔除集 {group}')
    subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/opportunity_trap_audit.py'),
                    '--states', f"BASE={ROOT / 'data/processed/a_share_daily_states_adopted.csv'}",
                    f"H2={EXP / 'states/H2_full/a_share_daily_states_adopted.csv'}",
                    '--trades', f"BASE={EXP / 'trades' / 'BASEfull*_trades.csv'}", f"H2={EXP / 'trades' / 'H2full*_trades.csv'}",
                    '--out', str(EXP / 'opportunity_trap.md')], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(ROOT / 'scripts/experimental/case_attribution.py'),
                    '--base', f"BASE={EXP / 'contrib_BASEfull20111101_trades.csv'}", '--arm', f"H2={EXP / 'contrib_H2full20111101_trades.csv'}",
                    '--base-states', str(EXP / 'states/BASE/a_share_daily_states_adopted.csv'),
                    '--arm-states', str(EXP / 'states/H2/a_share_daily_states_adopted.csv'), '--out', str(EXP / 'case_attribution.md')],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    last = {}
    for arm, path in (('BASE', ROOT / 'data/processed/a_share_daily_states_adopted.csv'), ('H2', EXP / 'states/H2_full/a_share_daily_states_adopted.csv')):
        with path.open(encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                if r['date'] == '2026-09-28':
                    last.setdefault(r['security_code'], {})[arm] = r['valuation_ratio']
    banks = {c: v for c, v in last.items() if v.get('BASE') != v.get('H2')}
    (EXP / 'current_banks.json').write_text(json.dumps(banks, ensure_ascii=False, indent=1) + '\n')


def main():
    for name in ('cache', 'nav', 'stats', 'errors', 'daily', 'trades'):
        (EXP / name).mkdir(exist_ok=True)
    rows = batch('full', [])
    top = {a: sorted(next(r for r in rows if r['arm'] == a and r['start'] == sw.EX5_ANCHOR_START)['前五赢家'].split('/')) for a in ARMS}
    A, U = top['BASE'], sorted(set(top['BASE']) | set(top['H2']))
    rows += batch('A', A)
    if U != A:
        rows += batch('U', U)
    with (EXP / 'summary_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    (EXP / 'run_manifest.json').write_text(json.dumps(dict(job_id=os.getenv('SLURM_JOB_ID'), base=sw.BASE, A=A, U=U, top=top), ensure_ascii=False, indent=1) + '\n')
    readings(A, U)


if __name__ == '__main__':
    main()
