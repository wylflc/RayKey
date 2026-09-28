"""OI-227 落地前重估（用户 2026-09-28 选定「同尺校准全期」、缩放银行 V）：非金融改用 v4.216 现行口径（研发资本化，
`../exp_oi213_20260928/` RD 臂，与安装的生产状态逐位相同）的月末 `P/V`，自 2007 年起；银行观测不变（v4.216 未改银行 V）。
同式回归得 c、b，银行 V 缩放系数 `k = exp(−c / b)`（银行在 1.0034 × k 上的预测回报等于非金融在 1.0034 上），等价银行线 `1.0034 × k`。

    python3 recalibrate_v4216.py     # → recalibration_v4216.json、nonfin_v4216.csv
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
sys.path.insert(0, str(EXP.parent / 'exp_oi213_20260928'))
import fairness as oi213  # noqa: E402
import calibrate  # noqa: E402

LINE = 1.0034


def main():
    oi213.START = '2007-01-01'
    rows = oi213.collect()
    nonfin = [dict(code=r['code'], month=r['month'], panel=r['panel'], pv=r['pv_G'], f3=r['f3'], f5=r['f5'])
              for r in rows if isinstance(r['pv_G'], float)]
    with (EXP / 'nonfin_v4216.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(nonfin[0])); w.writeheader(); w.writerows(nonfin)
    banks = []
    with (EXP / 'bank_observations.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            banks.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']),
                              f3=float(r['f3']) if r['f3'] not in ('', 'None') else None,
                              f5=float(r['f5']) if r['f5'] not in ('', 'None') else None))
    calibrate.LINE = LINE
    rng = np.random.default_rng(20260928)
    res = dict(line=LINE, nonfin_obs=len(nonfin), bank_obs=len(banks))
    for universe in ('面板', '全部'):
        for since, tag in (('2007-01', ''), ('2017-01', '2017起')):
            for h in calibrate.HORIZONS:
                key = f'{universe}{tag}_{h}y'
                e = calibrate.readout(banks, nonfin, h, universe, since, rng)
                e['k'] = float(np.exp(-e['c'] / e['b']))
                res[key] = e
                print(key, 'b %.4f' % e['b'], 'c %.4f' % e['c'], [round(v, 4) for v in e['c_ci']], 'k %.4f' % e['k'],
                      'L_b %.4f' % e['bank_line'], [round(v, 3) for v in e['bank_line_ci']], flush=True)
    (EXP / 'recalibration_v4216.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
