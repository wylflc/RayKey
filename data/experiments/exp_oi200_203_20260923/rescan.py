"""§12.1：新口径上换仓边际按 0.01 一档重扫 0.10～0.20（全样本 + 去赢家 A，14 起点，0bp）；只报读数，取值由用户裁定。"""
import csv
import json
import os
import shlex
import statistics as st
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from common import EXP, FROZEN_ACTIONS, ROOT, load, save
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw

MARGINS = [round(0.10 + 0.01 * i, 2) for i in range(11)]


def one(job):
    margin, start, group, excluded, width, states = job
    tag = sw.summary_tag(f'M{int(round(margin * 100)):02d}' + group, start, ','.join(excluded))
    args = shlex.split(sw.BASE)
    args[args.index('--swap-margin') + 1] = f'{margin:.2f}'
    args[args.index('--width') + 1] = width
    cmd = [sys.executable, str(EXP / 'engine.py'), *args, '--since', start, '--label-suffix', '_' + tag,
           '--out-dir', str(EXP / 'rescan_cache'), '--equity-bond-log-dir', str(EXP / 'rescan_daily'),
           '--daily-states', str(states / 'a_share_daily_states_adopted.csv'), '--hold-states', str(states / 'a_share_daily_states_hold.csv')]
    if excluded:
        cmd += ['--exclude-codes', ','.join(excluded)]
    with (EXP / 'errors' / f'{tag}.txt').open('w') as f:
        p = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=f, env=dict(os.environ, EXP_ACTIONS_FILE=str(FROZEN_ACTIONS)))
    assert p.returncode == 0, (tag, p.returncode)
    with (EXP / 'rescan_cache' / f'summary_{tag}.csv').open() as f:
        row = next(r for r in csv.DictReader(f) if r['策略'].startswith('trend_'))
    assert row['负现金日数'] == '0', tag
    return dict(margin=margin, start=start, group=group, tag=tag, **row)


def main():
    for name in ('rescan_cache', 'rescan_daily', 'errors', 'nav', 'stats'):
        (EXP / name).mkdir(exist_ok=True)
    ruling = load('user_ruling.json') if (EXP / 'user_ruling.json').exists() else {}
    align = load('align_check.json')['arms']['NEW']
    width = f"{ruling['width']:.4f}" if ruling.get('width') is not None else f"{align['width']:.4f}"
    states = EXP / 'states/NEW'
    A = load('winners.json')['A']
    jobs = [(m, s, g, ex, width, states) for m in MARGINS for s in sw.DEFAULT_STARTS for g, ex in (('full', []), ('A', A))]
    with ThreadPoolExecutor(max_workers=int(os.environ.get('SLURM_CPUS_PER_TASK', 16)) - 2) as pool:
        rows = list(pool.map(one, jobs))
    with (EXP / 'rescan_rows.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    base = next(m for m in MARGINS if abs(m - 0.15) < 1e-9)
    table = []
    for group in ('full', 'A'):
        ref = {r['start']: r for r in rows if r['group'] == group and r['margin'] == base}
        for m in MARGINS:
            sel = {r['start']: r for r in rows if r['group'] == group and r['margin'] == m}
            num = lambda r: {**{k: sw._field_value(r, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(r[sw.WIN5_KEY])}
            deltas_p = [100 * sw.start_delta(num(sel[s]), num(ref[s]), sw.WIN5_KEY) for s in sw.DEFAULT_STARTS]
            deltas_c = [100 * sw.start_delta(num(sel[s]), num(ref[s]), '年化') for s in sw.DEFAULT_STARTS]
            table.append(dict(group=group, margin=m, P_vs_015=st.median(deltas_p), CAGR_vs_015=st.median(deltas_c),
                              level_win5_median=st.median(100 * sw._field_value(r, '滚动5年年化中位') for r in sel.values()),
                              level_cagr_median=st.median(100 * sw._field_value(r, '年化') for r in sel.values()),
                              level_dd5_median=st.median(100 * sw._field_value(r, '滚动5年回撤中位') for r in sel.values())))
    save('rescan_table.json', dict(width=width, margins=MARGINS, rows=table, job_id=os.getenv('SLURM_JOB_ID')))
    for r in table:
        print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
