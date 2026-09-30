"""OI-245 第三段与 OI-246 共用观测（`preregister.md`「数据」「候选」；`../exp_oi246_20260930/preregister.md`「数据」「二」）。

在第二段口径（`../exp_oi245b_20260930/observations2.py`）上另挂带键、`eps_ttm`、`bps_operating` 与此前年报带的同名值，
逐行复现 `状态 V = 带 V ÷ 送转因子 − 累计现金`（相对差 < 1e-4，不符剔除），按以下候选近似重估 `P/V'`：

- LG1.3（第二段原式，复现核对）、LG1.3F／LG1.6F／LG2.0F（加当期 EPS 下限：`基数'' = min(基数, max(基数_LG, EPS_TTM × 估计股本))`）；
- R1（OI-246）：v > 0 的行 `基数' = min(基数, M5)`。

另出 OI-246 的利润比 PR（当期报表利润 ÷ 前 5 个财年年报报表利润中位）与账面比 BR（每股经营账面 ÷ 5 个财年前年报带同值）。

    python3 observations3.py     # → observations3.csv、observations3_check.json
"""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP.parent / 'exp_oi245b_20260930'))
sys.path.insert(0, str(EXP.parent / 'exp_oi245_20260930'))
import observations as obs1  # noqa: E402
import observations2 as ob2  # noqa: E402

# (名称, 阈值 T, 是否加 EPS 下限)
CANDIDATES = (('LG1.3', 1.3, False), ('LG1.3F', 1.3, True), ('LG1.6F', 1.6, True), ('LG2.0F', 2.0, True))
KEEP = ('roic_path', 'nopat_ps', 'shares_est', 'net_debt_ps', 'intrinsic_value', 'growth_trust', 'peak_weight', 'trough_weight',
        'roic_nopat_mode', 'eps_ttm', 'bps_operating')


def load_bands(codes):
    rows, annual = {}, defaultdict(list)
    num = obs1.num
    with obs1.BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            code = r['security_code']
            if code not in codes:
                continue
            rows[(code, r['report_date'], r['available_at'])] = {k: r.get(k, '') for k in KEEP}
            if r['status'] == 'ok' and r['report_date'].endswith('-12-31') and len(r['available_at']) == 10:
                nopat, shares, eps = num(r['nopat_ps']), num(r['shares_est']), num(r['eps_ttm'])
                annual[code].append(dict(fy=int(r['report_date'][:4]), av=r['available_at'],
                                         nopat=nopat * shares if nopat is not None and shares else None,
                                         profit=eps * shares if eps is not None and shares else None,
                                         bps_op=num(r['bps_operating'])))
    return rows, annual


def rescale(band, base, base2, factor, cash):
    """近似重估的状态 V'（企业价值按基数等比例缩放，同第二段）。"""
    v_band = obs1.num(band['intrinsic_value'])
    nd = obs1.num(band['net_debt_ps']) or 0.0
    v2 = ((v_band + nd) * base2 / base - nd) / factor - cash
    return v2 if v2 > 0 else float('nan')


def main():
    nonfin = obs1.load_nonfin()
    codes = {c for c, _ in nonfin}
    ends = ob2.month_ends(codes)
    bands, annual = load_bands(codes)
    gates, names = ob2.industries()
    check = dict(nonfin_rows=len(nonfin), matched=0, pv_mismatch=0, v_identity_mismatch=0, other_path=0, written=0,
                 changed={n: 0 for n, *_ in CANDIDATES + (('R1',),)}, nonpositive={n: 0 for n, *_ in CANDIDATES + (('R1',),)},
                 floor_binds={n: 0 for n, _, fl in CANDIDATES if fl})
    num = obs1.num
    out = []
    for key in sorted(nonfin):
        panel, pv, f3, f5 = nonfin[key]
        rec = ends.get(key)
        if rec is None:
            continue
        day, pv_s, rp, av, factor_s, cash_s, v_s = rec
        if not pv_s or abs(float(pv_s) / pv - 1.0) > 1e-4:
            check['pv_mismatch'] += 1
            continue
        check['matched'] += 1
        band = bands.get((key[0], rp, av))
        if band is None or band['roic_path'] not in obs1.PATHS:
            check['other_path'] += 1
            continue
        factor, cash, v_state = num(factor_s) or 1.0, num(cash_s) or 0.0, num(v_s)
        v_band = num(band['intrinsic_value'])
        if v_state is None or v_band is None or abs((v_band / factor - cash) / v_state - 1.0) > 1e-4:
            check['v_identity_mismatch'] += 1
            continue
        nopat, shares, eps = num(band['nopat_ps']), num(band['shares_est']), num(band['eps_ttm'])
        base = nopat * shares if nopat is not None and shares else None
        fy = int(rp[:4])
        hist = obs1.history(annual.get(key[0], []), fy, av, 5)
        prior = [a['nopat'] for a in hist if a['nopat'] is not None]
        m5 = statistics.median(prior) if len(prior) >= 3 else None
        prev = hist[-1]['nopat'] if hist and hist[-1]['fy'] == fy - 1 else None
        profits = [a['profit'] for a in hist if a['profit'] is not None]
        p5 = statistics.median(profits) if len(profits) >= 3 else None
        profit_now = eps * shares if eps is not None and shares else None
        old = [a for a in obs1.history(annual.get(key[0], []), fy, av, 5) if a['fy'] == fy - 5]
        bps_op = num(band['bps_operating'])
        lg = lambda a, b: obs1.clip(math.log(a / b), -1.0, 1.0) if a and b and a > 0 and b > 0 else None
        lam, v = num(band['growth_trust']), num(band['trough_weight'])
        row = dict(code=key[0], name=names.get(key[0], ''), gate=gates.get(key[0], 'NA'), month=key[1], date=day, panel=panel,
                   pv=pv, f3=f3, f5=f5, path=band['roic_path'], mode=band['roic_nopat_mode'], lam=lam,
                   w=num(band['peak_weight']), v=v, F1=lg(base, m5), f1_recent=lg(base, prev), f1_old=lg(prev, m5),
                   base=base, m5=m5, report_date=rp, available_at=av, eps_ttm=eps, shares_est=shares, profit_now=profit_now,
                   profit_m5=p5, pr=profit_now / p5 if profit_now is not None and p5 and p5 > 0 else None,
                   bps_op=bps_op, br=bps_op / old[0]['bps_op'] if old and old[0]['bps_op'] and bps_op else None)
        floor_total = eps * shares if eps is not None and eps > 0 and shares else None
        for name, t, floor in CANDIDATES:
            w_l, base_lg = ob2.guard(base, m5, lam, t, False)
            if w_l == 0.0:
                row[f'pv_{name}'] = pv
                continue
            base2 = base_lg
            if floor and floor_total is not None:
                base2 = min(base, max(base_lg, floor_total))
                if base2 > base_lg + 1e-9:
                    check['floor_binds'][name] += 1
                    row[f'floor_{name}'] = True
            if abs(base2 - base) < 1e-9 * abs(base):
                row[f'pv_{name}'] = pv
                continue
            v2 = rescale(band, base, base2, factor, cash)
            if v2 != v2:
                row[f'pv_{name}'] = None
                check['nonpositive'][name] += 1
            else:
                row[f'pv_{name}'] = pv * v_state / v2
                check['changed'][name] += 1
        if v and v > 0 and base and m5 and base > m5:
            v2 = rescale(band, base, m5, factor, cash)
            row['pv_R1'] = pv * v_state / v2 if v2 == v2 else None
            check['changed' if v2 == v2 else 'nonpositive']['R1'] += 1
        else:
            row['pv_R1'] = pv
        out.append(row)
    check['written'] = len(out)
    fields = list(dict.fromkeys(k for r in out for k in r))
    with (EXP / 'observations3.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(out)
    (EXP / 'observations3_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')
    print(check, flush=True)


if __name__ == '__main__':
    main()
