"""OI-232 登记核查：保险未做同尺校准（2026-09-29，用户看过招行／平安 P/V 拆解后要求登记）。

读数一（09-28 信号日拆解）：招行与五家 A 股保险的 V_D0、自身 V_DDM（COE 10%）、当日银行截面 G 与同尺系数 k；
招行与平安按四把尺子的 `P/V`（收盘取 `data/processed/daily_buy_candidates.csv` 的 09-28 行）。全部调用生产模块
`bank_valuation` 与 `screen_daily_volume_price_signals`，与 09-28 计划同源。

读数二（保险同尺偏差的初步读数，不是预登记检验）：OI-227 口径（`../exp_oi227_20260928/calibrate.py` 的 `readout`）
`log(1 + f_h) = a_月 + b·log(P/V) + c·保险`，共同斜率，按股票整簇自助 1000 次，`k_ins = exp(−c ÷ b)`。保险取 v4.221 生产
逐日状态（保险 V = V_D0，不乘 k）的月末 `P/V`；非金融取 `../exp_oi227_20260928/nonfin_v4216.csv`（v4.216 起非金融口径未变）。
面板只有平安一只保险：面板读数是单只股票的读数，自助区间不含保险之间的抽样误差。

    python3 evidence.py    # → evidence.json、insurer_observations.csv
"""
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
sys.path.insert(0, str(ROOT / 'data/experiments/exp_oi227_20260928'))
import bank_valuation as bv  # noqa: E402
import build_historical_valuation_bands as bhv  # noqa: E402
import calibrate as oi227  # noqa: E402
import screen_daily_volume_price_signals as scan  # noqa: E402
from divspread_dividend import annual_dividend  # noqa: E402
from divspread_names import INSURER_CODES  # noqa: E402
from moat_param_lab import forward_annualized, total_return_index  # noqa: E402

SIGNAL = '2026-09-28'
CMB, PINGAN = '600036', '601318'
LINE = 1.0034
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
CANDIDATES = ROOT / 'data/processed/daily_buy_candidates.csv'
NONFIN = ROOT / 'data/experiments/exp_oi227_20260928/nonfin_v4216.csv'
KEYS = {'n_banks': 'n_ins', 'bank_codes': 'ins_codes', 'bank_line': 'ins_line', 'bank_line_ci': 'ins_line_ci',
        'bank_slope': 'ins_slope', 'bank_slope_ci': 'ins_slope_ci', 'bank_zone_share_at_line': 'ins_zone_share_at_line',
        'bank_zone_share_at_bank_line': 'ins_zone_share_at_ins_line'}


def rnd(v, n=4):
    return round(v, n) if isinstance(v, float) else v


def decomposition() -> dict:
    rf = scan._default_rf(SIGNAL)
    acts = scan._corporate_actions()
    dists = scan._dividend_distributions()
    banks = bv.bank_codes(ROOT / 'data/raw/a_share_securities.csv')
    fund = bv.BankFundamentals(ROOT / 'data/processed/roic_bands.csv', banks | INSURER_CODES)
    pairs = {c: (scan.bank_dividend_intrinsic(c, SIGNAL, rf), bv.ddm_at(fund, acts.get(c, []), c, SIGNAL)) for c in sorted(banks)}
    g = bv.h2_scale(pairs.values())
    ratios = sorted(d0 / dd for d0, dd in pairs.values() if d0 and dd and d0 > 0 and dd > 0)
    with CANDIDATES.open(newline='', encoding='utf-8') as f:
        closes = {r['security_code']: float(r['close']) for r in csv.DictReader(f) if r['trade_date'] == SIGNAL}
    out = dict(signal_date=SIGNAL, rf=rf, bank_G=g, bank_k=bv.BANK_SCALE, banks_in_G=len(ratios),
               bank_d0_over_ddm=dict(p10=ratios[len(ratios) // 10], median=float(np.median(ratios)),
                                     p90=ratios[len(ratios) * 9 // 10]), companies={})
    for c in [CMB] + sorted(INSURER_CODES):
        d0 = scan.bank_dividend_intrinsic(c, SIGNAL, rf)
        f = fund.at(c, SIGNAL)
        dd = bv.ddm_at(fund, acts.get(c, []), c, SIGNAL)
        prod, method = scan.bank_live_value(c, SIGNAL, rf)
        e = dict(annual_dividend=annual_dividend(dists.get(c, []), SIGNAL),
                 fundamentals=dict(available_at=f[0], bps=f[1], roe0=f[2], payout=f[3]) if f else None,
                 v_d0=d0, v_ddm=dd, d0_over_ddm=d0 / dd if d0 and dd else None,
                 v_bank_ruler=dd * g * bv.BANK_SCALE if dd else None, v_production=prod, production_method=method)
        if c in closes:
            p = closes[c]
            e['close'] = p
            e['pv'] = dict(production=p / prod, own_d0=p / d0, own_ddm=p / dd, bank_ruler=p / e['v_bank_ruler'])
        out['companies'][c] = e
    cmb, pa = out['companies'][CMB]['pv'], out['companies'][PINGAN]['pv']
    out['pv_gap_cmb_minus_pingan'] = {k: cmb[k] - pa[k] for k in cmb}
    return out


def insurer_rows() -> list[dict]:
    """OI-227 `bank_rows` 同式，代码换成保险；逐行前缀过滤后再解析。"""
    prefixes = tuple(c + ',' for c in INSURER_CODES)
    ends = {}
    with STATES.open(newline='', encoding='utf-8') as f:
        header = next(csv.reader([f.readline()]))
        ic, idt, ipv = (header.index(k) for k in ('security_code', 'date', 'valuation_ratio'))
        for line in f:
            if not line.startswith(prefixes):
                continue
            row = next(csv.reader([line]))
            if row[idt] < oi227.START or not row[ipv]:
                continue
            key = (row[ic], row[idt][:7])
            if key not in ends or row[idt] > ends[key][0]:
                ends[key] = (row[idt], float(row[ipv]))
    actions = bhv.load_actions()
    sp = oi227.spans()
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
            fwd = {h: forward_annualized(tr, days, day, h) for h in oi227.HORIZONS}
            out.append(dict(code=code, month=key[1], date=day, panel=any(a <= day <= b for a, b in sp.get(code, ())), pv=pv,
                            f3=fwd[3], f5=fwd[5]))
    return out


def nonfin_rows() -> list[dict]:
    out = []
    with NONFIN.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            f3 = float(r['f3']) if r['f3'] not in ('', 'None') else None
            f5 = float(r['f5']) if r['f5'] not in ('', 'None') else None
            out.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=float(r['pv']), f3=f3, f5=f5))
    return out


def calibration(ins: list[dict], nonfin: list[dict]) -> dict:
    oi227.LINE = LINE
    rng = np.random.default_rng(20260929)
    out = {}
    for universe in ('面板', '全部'):
        for since, tag in (('2007-01', ''), ('2017-01', '2017起')):
            for h in oi227.HORIZONS:
                key = f'{universe}{tag}_{h}y'
                try:
                    e = oi227.readout(ins, nonfin, h, universe, since, rng)
                except (np.linalg.LinAlgError, IndexError, ValueError) as err:
                    out[key] = dict(error=repr(err))
                    print(key, 'error', repr(err), flush=True)
                    continue
                e = {KEYS.get(k, k): v for k, v in e.items()}
                e['k_ins'] = float(math.exp(-e['c'] / e['b']))
                out[key] = e
                print(key, 'ins', e['n_ins'], e['ins_codes'], 'b %.4f' % e['b'], 'c %.4f' % e['c'], [round(v, 4) for v in e['c_ci']],
                      'k_ins %.4f' % e['k_ins'], 'zone %.3f vs nonfin %.3f' % (e['ins_zone_share_at_line'], e['nonfin_zone_share']), flush=True)
    return out


def finite(o):
    """JSON 不收 NaN／Infinity：单只保险时保险内斜率无定义，记 null。"""
    if isinstance(o, dict):
        return {k: finite(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [finite(v) for v in o]
    return o if not isinstance(o, float) or math.isfinite(o) else None


def main():
    dec = decomposition()
    for c, e in dec['companies'].items():
        print(c, {k: rnd(v) for k, v in e.items() if k not in ('fundamentals', 'pv')}, {k: rnd(v) for k, v in (e.get('pv') or {}).items()})
    ins = insurer_rows()
    with (EXP / 'insurer_observations.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(ins[0])); w.writeheader(); w.writerows(ins)
    per_code = {}
    for r in ins:
        s = per_code.setdefault(r['code'], dict(months=0, panel_months=0, pv=[]))
        s['months'] += 1
        s['panel_months'] += r['panel']
        s['pv'].append(r['pv'])
    summary = {c: dict(months=s['months'], panel_months=s['panel_months'], pv_median=float(np.median(s['pv'])),
                       zone_share=float(np.mean([v <= LINE for v in s['pv']]))) for c, s in sorted(per_code.items())}
    res = dict(decomposition=dec, insurer_obs=len(ins), insurer_summary=summary, line=LINE,
               calibration=calibration(ins, nonfin_rows()))
    (EXP / 'evidence.json').write_text(json.dumps(finite(res), ensure_ascii=False, indent=1, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
