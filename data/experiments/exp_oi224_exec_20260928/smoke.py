"""补丁冒烟：引擎副本（scripts/_oi224_bt_wip.py）不开新开关须逐字段复现在册 BASE 锚点；RE120 与 DPs0.7e 能跑通。"""
import csv, json, shlex, subprocess, sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
out = EXP / 'smoke'; out.mkdir(exist_ok=True)
start = sw.EX5_ANCHOR_START
runs = {'BASE': [], 'RE120': ['--reentry-days', '120'],
        'DPs07e': ['--swap-out-min-pv', '0.7', '--swap-protect-e1', '--e1-table', str(EXP / 'e1_table.csv')]}
res = {}
for label, extra in runs.items():
    tag = sw.summary_tag(label, start, '')
    cmd = [sys.executable, str(ROOT / 'scripts/_oi224_bt_wip.py'), *shlex.split(sw.BASE), *extra, '--since', start,
           '--label-suffix', '_' + tag, '--out-dir', str(out)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (out / f'{label}.log').write_text(p.stdout[-20000:] + '\n---\n' + p.stderr[-20000:])
    assert p.returncode == 0, (label, p.stderr[-2000:])
    row = next(r for r in csv.DictReader((out / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))
    res[label] = {k: row[k] for k in ('年化', '最大回撤', '期末净资产', '换仓次数') if k in row}
reg = next(r for r in csv.DictReader((sw.OUT_DIR / f'summary_{sw.summary_tag("BASE", start, "")}.csv').open()) if r['策略'].startswith('trend_'))
diffs = {k: [reg[k], v] for k, v in res['BASE'].items() if reg.get(k) != v}
res['reproduces_registered_base'] = not diffs
res['diffs'] = diffs
(EXP / 'smoke.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
print(json.dumps(res, ensure_ascii=False))
