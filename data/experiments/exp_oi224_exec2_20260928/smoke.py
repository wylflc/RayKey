"""补丁冒烟：引擎副本（scripts/_oi224_bt_wip2.py）不开新开关须逐字段复现在册 BASE 锚点（v4.215）；LS／DPt／SZ 及 E1 变体能跑通并记下触发计数。"""
import csv, json, re, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
out = EXP / 'smoke'; out.mkdir(exist_ok=True)
start = sw.EX5_ANCHOR_START
E1 = ['--e1-table', str(ROOT / 'data/experiments/exp_oi224_exec_20260928/e1_table.csv')]
runs = {'BASE': [], 'LS20': ['--left-stop', '0.20'], 'LS20e': ['--left-stop', '0.20', '--left-e1', *E1],
        'DPt07': ['--deep-stop-pv', '0.7'], 'DPt07e': ['--deep-stop-pv', '0.7', '--deep-stop-e1', *E1],
        'SZ0': ['--size-breaks', '0.6', '0.85'], 'SZ0e': ['--size-breaks', '0.6', '0.85', '--size-e1', *E1]}


def one(item):
    label, extra = item
    tag = sw.summary_tag(label, start, '')
    cmd = [sys.executable, str(ROOT / 'scripts/_oi224_bt_wip2.py'), *shlex.split(sw.BASE), *extra, '--since', start,
           '--label-suffix', '_' + tag, '--out-dir', str(out), '--trade-log', str(out / f'ledger_{label}.csv')]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (out / f'{label}.log').write_text(p.stdout[-40000:] + '\n---\n' + p.stderr[-20000:])
    assert p.returncode == 0, (label, p.stderr[-2000:])
    row = next(r for r in csv.DictReader((out / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))
    return label, row


with ThreadPoolExecutor(max_workers=len(runs)) as pool:
    rows = dict(pool.map(one, runs.items()))
reg = next(r for r in csv.DictReader((sw.OUT_DIR / f'summary_{sw.summary_tag("BASE", start, "")}.csv').open()) if r['策略'].startswith('trend_'))
fields = [*sw.FIELDS, sw.WIN5_KEY]
diffs = {k: [reg[k], rows['BASE'][k]] for k in fields if reg.get(k) != rows['BASE'].get(k)}
res = dict(reproduces_registered_base=not diffs, diffs=diffs, fields=len(fields))
for label, row in rows.items():
    log = (out / f'{label}.log').read_text()
    hits = dict(re.findall(r'((?:左侧半档|T\+1确认·左侧半档)[^\s｜]*) ([\d,]+)', log))
    reasons = {}
    with (out / f'ledger_{label}.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            for s in ('左侧半档', '深度低估'):
                if s in (r.get('reason') or ''):
                    reasons[s] = reasons.get(s, 0) + 1
    res[label] = dict(cagr=row.get('年化'), mdd=row.get('最大回撤'), swaps=row.get('换仓次数'), log_hits=hits, ledger_reasons=reasons)
(EXP / 'smoke.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
print(json.dumps(res, ensure_ascii=False))
