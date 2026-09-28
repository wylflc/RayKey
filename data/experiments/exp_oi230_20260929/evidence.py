"""OI-230 核查：平安银行历史 V 偏低的原因（银行 DDM 终值派息率与终值增长不一致）。

    python3 evidence.py   # → evidence.json（三组读数），标准输出同步打印

1. 平安银行逐年：`bank_valuation.ddm_value`（现行）、终值改用可持续派息率 1 − g_T/ROE_T 的 DDM、同一路径的 RI；
2. v4.219 生产状态上银行截面按派息率分组的 `P/V`（2016-06-20、2020-06-22）；
3. OI-207 月末观测（exp_oi207_20260928/observations.csv，2010 起）上现行 DDM10 对 RI10（= 终值一致 DDM）的
   银行截面排序 IC 配对差，以及派息率成分 log(P/V_DDM10 ÷ P/V_RI10) 对其后回报的 IC（Newey-West t，滞后 12×年数）。
"""
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import bank_valuation as bv  # noqa: E402

STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
BANDS = ROOT / 'data/processed/roic_bands.csv'
SECURITIES = ROOT / 'data/raw/a_share_securities.csv'
OBS = ROOT / 'data/experiments/exp_oi207_20260928/observations.csv'
DATES = ('2016-06-20', '2020-06-22')


def consistent_ddm(bps, roe0, payout, coe=bv.COE):
    """同一 ROE／BV 路径，终值期派息率取与 g_T 一致的可持续派息率（清洁盈余一致）；派息率为 0 也可估。"""
    path, roe_t, g_t, bv_n, b = bv.roe_bv_path(bps, roe0, payout, coe)
    pay = 1.0 - b
    pv = sum(r * prev * pay / (1 + coe) ** t for t, (r, prev) in enumerate(path, start=1))
    return pv + roe_t * bv_n * (1 - g_t / roe_t) / (coe - g_t) / (1 + coe) ** bv.FADE_YEARS


def residual_income(bps, roe0, payout, coe=bv.COE):
    path, roe_t, g_t, bv_n, b = bv.roe_bv_path(bps, roe0, payout, coe)
    pv = sum((r - coe) * prev / (1 + coe) ** t for t, (r, prev) in enumerate(path, start=1))
    return bps + pv + (roe_t - coe) * bv_n / (coe - g_t) / (1 + coe) ** bv.FADE_YEARS


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def spearman(x, y):
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def nw_t(series, lag):
    x = np.asarray(series, float)
    n = len(x)
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n))


def pingan_path():
    out = []
    with BANDS.open(encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r['security_code'] == '000001' and r['report_date'].endswith('12-31')]
    for r in sorted(rows, key=lambda r: r['available_at']):
        b, roe, pay = num(r['bps']), num(r['roe0']), num(r['payout'])
        if not b or not roe or roe <= 0:
            continue
        cur = bv.ddm_value(b, roe, pay)
        _path, roe_t, g_t, _bvn, _b = bv.roe_bv_path(b, roe, pay, bv.COE)
        out.append(dict(report=r['report_date'], available_at=r['available_at'], bps=b, roe0=roe, payout=pay,
                        ddm_current=cur, ddm_current_over_bps=cur / b if cur else None,
                        ddm_consistent=consistent_ddm(b, roe, pay), ri=residual_income(b, roe, pay),
                        sustainable_payout=1 - g_t / roe_t))
    return out


def cross_section():
    codes = bv.bank_codes(SECURITIES)
    fund = bv.BankFundamentals(BANDS, codes)
    with SECURITIES.open(encoding='utf-8-sig') as f:
        names = {r['security_code'].zfill(6): r['security_name'] for r in csv.DictReader(f)}
    want = {(c, d) for c in codes for d in DATES}
    st = {}
    with STATES.open(encoding='utf-8') as f:
        rd = csv.reader(f)
        h = next(rd)
        ic, idt, iv, ipv = h.index('security_code'), h.index('date'), h.index('intrinsic_value'), h.index('valuation_ratio')
        for row in rd:
            if (row[ic], row[idt]) in want:
                st[(row[ic], row[idt])] = (num(row[iv]), num(row[ipv]))
    out = {}
    for d in DATES:
        banks = []
        for c in sorted(codes):
            f = fund.at(c, d)
            if not f or (c, d) not in st or not f[1] or not f[2] or f[2] <= 0:
                continue
            _, b, roe, pay, _ = f
            cur = bv.ddm_value(b, roe, pay)
            banks.append(dict(code=c, name=names.get(c, ''), payout=pay, roe0=roe, ddm_current_over_bps=cur / b if cur else None,
                              ddm_consistent_over_bps=consistent_ddm(b, roe, pay) / b, pv=st[(c, d)][1]))
        lo = [x['pv'] for x in banks if x['payout'] is not None and x['payout'] < 0.20 and x['pv']]
        hi = [x['pv'] for x in banks if x['payout'] is not None and x['payout'] >= 0.25 and x['pv']]
        out[d] = dict(banks=banks, low_payout_n=len(lo), low_payout_pv_median=statistics.median(lo) if lo else None,
                      high_payout_n=len(hi), high_payout_pv_median=statistics.median(hi) if hi else None,
                      rank_corr_payout_pv=spearman([x['payout'] for x in banks if x['pv']], [x['pv'] for x in banks if x['pv']]))
    return out


def paired_ic():
    with OBS.open(encoding='utf-8') as f:
        rows = [r for r in csv.DictReader(f) if r['insurer'] == 'False']
    out = {}
    for panel_only in (False, True):
        for h in (1, 2, 3):
            by = defaultdict(list)
            for r in rows:
                if panel_only and r['panel'] != 'True':
                    continue
                a, b, fr = num(r['DDM10']), num(r['RI10']), num(r[f'f{h}'])
                if a and b and a > 0 and b > 0 and fr is not None:
                    by[r['month']].append((a, b, fr))
            d_ic, r_ic, pay_ic = [], [], []
            for _m, v in sorted(by.items()):
                if len(v) < 10:
                    continue
                y = [x[2] for x in v]
                d_ic.append(spearman([math.log(x[0]) for x in v], y))
                r_ic.append(spearman([math.log(x[1]) for x in v], y))
                pay_ic.append(spearman([math.log(x[0]) - math.log(x[1]) for x in v], y))
            diff = [a - b for a, b in zip(d_ic, r_ic)]
            out[f"{'panel' if panel_only else 'all'}_{h}y"] = dict(
                months=len(diff), ddm10=float(np.mean(d_ic)), ri10=float(np.mean(r_ic)), diff=float(np.mean(diff)),
                diff_nw_t=nw_t(diff, 12 * h), payout_component_ic=float(np.mean(pay_ic)), payout_component_nw_t=nw_t(pay_ic, 12 * h))
    return out


def main():
    res = dict(pingan=pingan_path(), cross_section=cross_section(), paired_ic=paired_ic())
    for r in res['pingan']:
        print(r['report'], r['available_at'], f"BPS {r['bps']:.2f} ROE0 {r['roe0']:.3f} 派息率 " + (f"{r['payout']:.3f}" if r['payout'] is not None else "缺（按 0.30）"),
              f"现行 DDM {r['ddm_current']:.3f}" if r['ddm_current'] else '现行 DDM 空', f"一致 DDM {r['ddm_consistent']:.3f} RI {r['ri']:.3f}")
    for d, x in res['cross_section'].items():
        print(d, f"派息率<20% {x['low_payout_n']} 家 P/V 中位 {x['low_payout_pv_median']:.3f}；≥25% {x['high_payout_n']} 家 {x['high_payout_pv_median']:.3f}；"
                 f"派息率与 P/V 秩相关 {x['rank_corr_payout_pv']:.3f}")
    for k, x in res['paired_ic'].items():
        print(k, f"DDM10 {x['ddm10']:.3f} RI10 {x['ri10']:.3f} 差 {x['diff']:+.3f}（t {x['diff_nw_t']:+.2f}）"
                 f" 派息率成分 IC {x['payout_component_ic']:+.3f}（t {x['payout_component_nw_t']:+.2f}）")
    (EXP / 'evidence.json').write_text(json.dumps(res, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
