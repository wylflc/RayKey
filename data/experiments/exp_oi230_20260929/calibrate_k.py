"""OI-230 读数 V3：同尺系数 k 的重估（OI-227 口径，preregister.md）。

银行观测取 CONTROL_RAW／DC_RAW（不缩放）候选侧逐日状态的银行（不含保险）月末 `P/V`，非金融观测取 v4.216 现行口径
`exp_oi227_20260928/nonfin_v4216.csv`；`log(1 + f_h) = a_月 + b·log(P/V) + c·银行`，`k = exp(−c ÷ b)`，按股票整簇自助。
主读数 = 面板在册、2007 年起、3 年（OI-227 裁定的「同尺校准全期」）；CONTROL_RAW 须复现 0.6951。

    python3 calibrate_k.py    # → calibration.json（k_dc 供 build.py 第三段），bank_observations_<臂>.csv
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'data/experiments/exp_oi227_20260928'))
import calibrate as oi227  # noqa: E402

NONFIN = ROOT / 'data/experiments/exp_oi227_20260928/nonfin_v4216.csv'
MAIN = '面板_3y'
CURRENT_K = 0.6951


def nonfin_rows():
    out = []
    with NONFIN.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            f3 = float(r['f3']) if r['f3'] not in ('', 'None') else None
            f5 = float(r['f5']) if r['f5'] not in ('', 'None') else None
            out.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']), f3=f3, f5=f5))
    return out


def main():
    nonfin = nonfin_rows()
    oi227.LINE = 1.0034
    res = dict(nonfin_obs=len(nonfin), main=MAIN)
    for arm in ('CONTROL_RAW', 'DC_RAW'):
        oi227.STATES = EXP / 'states' / f'{arm}_build' / 'a_share_daily_states_adopted.csv'
        banks = oi227.bank_rows()
        with (EXP / f'bank_observations_{arm}.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(banks[0])); w.writeheader(); w.writerows(banks)
        rng = np.random.default_rng(20260929)
        entry = dict(bank_obs=len(banks))
        for universe in ('面板', '全部'):
            for since, tag in (('2007-01', ''), ('2017-01', '2017起')):
                for h in oi227.HORIZONS:
                    key = f'{universe}{tag}_{h}y'
                    e = oi227.readout(banks, nonfin, h, universe, since, rng)
                    e['k'] = float(np.exp(-e['c'] / e['b']))
                    entry[key] = e
                    print(arm, key, 'b %.4f' % e['b'], 'c %.4f' % e['c'], [round(v, 4) for v in e['c_ci']], 'k %.4f' % e['k'], flush=True)
        res[arm] = entry
    k_control = res['CONTROL_RAW'][MAIN]['k']
    res['control_k_check'] = dict(k=k_control, registered=CURRENT_K, reproduced=abs(k_control - CURRENT_K) < 5e-4)
    res['k_dc'] = round(res['DC_RAW'][MAIN]['k'], 4)
    (EXP / 'calibration.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    print('k check', res['control_k_check'], 'k_dc', res['k_dc'], flush=True)
    if not res['control_k_check']['reproduced']:
        print('WARNING：CONTROL_RAW 未复现 k = 0.6951，读数须先查明原因', flush=True)


if __name__ == '__main__':
    main()
