"""补丁冒烟：引擎副本（scripts/_oi227_bt_wip.py）不开开关须逐字段复现在册 BASE 锚点（v4.215）；BL0677 能跑通且银行新建仓的 P/V 都 ≤ 0.677。"""
import csv, json, shlex, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw
import bank_valuation
out = EXP / 'smoke'; out.mkdir(exist_ok=True)
start = sw.EX5_ANCHOR_START
runs = {'BASE': [], 'BL0677': ['--bank-buy-line', '0.677']}


def one(item):
    label, extra = item
    tag = sw.summary_tag(label, start, '')
    cmd = [sys.executable, str(ROOT / 'scripts/_oi227_bt_wip.py'), *shlex.split(sw.BASE), *extra, '--since', start,
           '--label-suffix', '_' + tag, '--out-dir', str(out), '--trade-log', str(out / f'ledger_{label}.csv')]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (out / f'{label}.log').write_text(p.stdout[-20000:] + '\n---\n' + p.stderr[-20000:])
    assert p.returncode == 0, (label, p.stderr[-2000:])
    return label, next(r for r in csv.DictReader((out / f'summary_{tag}.csv').open()) if r['策略'].startswith('trend_'))


with ThreadPoolExecutor(max_workers=2) as pool:
    rows = dict(pool.map(one, runs.items()))
reg = next(r for r in csv.DictReader((sw.OUT_DIR / f'summary_{sw.summary_tag("BASE", start, "")}.csv').open()) if r['策略'].startswith('trend_'))
fields = [*sw.FIELDS, sw.WIN5_KEY]
diffs = {k: [reg[k], rows['BASE'][k]] for k in fields if reg.get(k) != rows['BASE'].get(k)}
banks = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
res = dict(reproduces_registered_base=not diffs, diffs=diffs)
for label in runs:
    with (out / f'ledger_{label}.csv').open(newline='', encoding='utf-8') as f:
        buys = [r for r in csv.DictReader(f) if r['action'] == '买入' and r['security_code'] in banks]
    res[label] = dict(cagr=rows[label]['年化'], bank_buys=len(buys),
                      bank_first_buys=sum(r['reason'] == '首次建仓' for r in buys),
                      bank_first_buy_max_pv=max((float(r['pv_ratio']) for r in buys if r['reason'] == '首次建仓'), default=None))
(EXP / 'smoke.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
print(json.dumps(res, ensure_ascii=False))
