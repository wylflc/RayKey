"""OI-227 第一步：同尺校准的银行偏差 c 与折算的银行买入线（preregister.md 读数 1）。

非金融观测取 `../exp_oi223_20260928/cache/fairness_observations_TIERS.csv` 的 CONTROL 列（v4.215 现行口径，逐行复现生产）；
银行观测取现行生产逐日状态（v4.215 H2）银行行的月末 `P/V`，前向 3／5 年含分红年化回报同式计算（保险除外）。
回归 `log(1 + f_h) = a_月 + b·log(P/V) + c·银行`（共同斜率），按股票整簇自助 1000 次；
银行线 `L_b = L × exp(−c / b)`（使银行在线上的预测回报等于非金融在 L 上），L = 1.0495。另报 2017 年起子样本与银行内部斜率。

    python3 calibrate.py     # → calibration.json、bank_observations.csv
"""
import bisect
import csv
import json
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import bank_valuation  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
from moat_param_lab import forward_annualized, total_return_index  # noqa: E402

LINE = 1.0495
NONFIN = ROOT / 'data/experiments/exp_oi223_20260928/cache/fairness_observations_TIERS.csv'
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
START = '2007-01-01'
PV_RANGE = (0.2, 5.0)
BOOT = 1000
HORIZONS = (3, 5)


def spans():
    out = {}
    with PANEL.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            out.setdefault(r['security_code'].zfill(6), []).append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
    return out


def bank_rows():
    codes = bank_valuation.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    ends = {}
    with STATES.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, ipv = (h.index(k) for k in ('security_code', 'date', 'valuation_ratio'))
        for row in reader:
            code = row[ic]
            if code not in codes or row[idt] < START or not row[ipv]:
                continue
            key = (code, row[idt][:7])
            if key not in ends or row[idt] > ends[key][0]:
                ends[key] = (row[idt], float(row[ipv]))
    actions = bhv.load_actions()
    sp = spans()
    out = []
    for code in sorted({k[0] for k in ends}):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, actions.get(code, []))
        for key in sorted(k for k in ends if k[0] == code):
            day, pv = ends[key]
            if day not in tr or pv <= 0:
                continue
            fwd = {h: forward_annualized(tr, days, day, h) for h in HORIZONS}
            out.append(dict(code=code, month=key[1], date=day, panel=any(a <= day <= b for a, b in sp.get(code, ())), pv=pv,
                            f3=fwd[3], f5=fwd[5]))
    return out


def nonfin_rows():
    out = []
    with NONFIN.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            try:
                pv = float(r['pv_C'])
            except ValueError:
                continue
            f3 = float(r['f3']) if r['f3'] not in ('', 'None') else None
            f5 = float(r['f5']) if r['f5'] not in ('', 'None') else None
            out.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=pv, f3=f3, f5=f5))
    return out


def fit(y, x, z, t, w):
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    cols = [c - (np.bincount(t, weights=w * c) / safe)[t] for c in (y, x, z)]
    X = np.column_stack(cols[1:])
    Xw = X * w[:, None]
    return np.linalg.solve(X.T @ Xw, Xw.T @ cols[0])


def fit_bank_slope(y, x, t, w):
    tot = np.bincount(t, weights=w)
    safe = np.where(tot > 0, tot, 1.0)
    yc, xc = (c - (np.bincount(t, weights=w * c) / safe)[t] for c in (y, x))
    return float((w * xc) @ yc / ((w * xc) @ xc))


def readout(banks, nonfin, h, universe, since, rng):
    pick = lambda r: (r['panel'] or universe == '全部') and r['month'] >= since and r[f'f{h}'] is not None and PV_RANGE[0] <= r['pv'] <= PV_RANGE[1]
    sample = [dict(r, bank=0.0) for r in nonfin if pick(r)] + [dict(r, bank=1.0) for r in banks if pick(r)]
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in sample}))}
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
    y = np.log1p(np.array([r[f'f{h}'] for r in sample]))
    x = np.log(np.array([r['pv'] for r in sample]))
    z = np.array([r['bank'] for r in sample])
    t = np.array([months[r['month']] for r in sample])
    s = np.array([codes[r['code']] for r in sample])
    bm = z == 1
    beta = fit(y, x, z, t, np.ones(len(y)))
    draws, bank_b = [], []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s]
        try:
            d = fit(y, x, z, t, w)
        except np.linalg.LinAlgError:
            continue
        draws.append(d)
        if (w * bm).sum() > 0:
            bank_b.append(fit_bank_slope(y[bm], x[bm], t[bm], w[bm]))
    draws = np.array(draws)
    lines = LINE * np.exp(-draws[:, 1] / draws[:, 0])
    ci = lambda v: [float(np.percentile(v, 5)), float(np.percentile(v, 50)), float(np.percentile(v, 95))]
    bank_pv = np.exp(x[bm])
    return dict(n_banks=int(bm.sum()), bank_codes=len({r['code'] for r in sample if r['bank']}), n_nonfin=int((~bm).sum()),
                b=float(beta[0]), b_ci=ci(draws[:, 0]), c=float(beta[1]), c_ci=ci(draws[:, 1]),
                bank_line=float(LINE * np.exp(-beta[1] / beta[0])), bank_line_ci=ci(lines),
                bank_slope=fit_bank_slope(y[bm], x[bm], t[bm], np.ones(int(bm.sum()))), bank_slope_ci=ci(bank_b),
                bank_zone_share_at_line=float((bank_pv <= LINE).mean()),
                bank_zone_share_at_bank_line=float((bank_pv <= LINE * np.exp(-beta[1] / beta[0])).mean()),
                nonfin_zone_share=float((np.exp(x[~bm]) <= LINE).mean()))


def main():
    banks = bank_rows()
    with (EXP / 'bank_observations.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(banks[0])); w.writeheader(); w.writerows(banks)
    nonfin = nonfin_rows()
    rng = np.random.default_rng(20260928)
    res = dict(line=LINE, boot=BOOT, bank_obs=len(banks), nonfin_obs=len(nonfin))
    for universe in ('面板', '全部'):
        for since, tag in (('2007-01', ''), ('2017-01', '2017起')):
            for h in HORIZONS:
                key = f'{universe}{tag}_{h}y'
                res[key] = readout(banks, nonfin, h, universe, since, rng)
                e = res[key]
                print(key, 'banks', e['n_banks'], e['bank_codes'], 'b %.3f' % e['b'], 'c %.4f' % e['c'], [round(v, 4) for v in e['c_ci']],
                      'L_b %.3f' % e['bank_line'], [round(v, 3) for v in e['bank_line_ci']], 'bank slope %.3f' % e['bank_slope'],
                      'zone share bank %.3f→%.3f nonfin %.3f' % (e['bank_zone_share_at_line'], e['bank_zone_share_at_bank_line'], e['nonfin_zone_share']),
                      flush=True)
    (EXP / 'calibration.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
