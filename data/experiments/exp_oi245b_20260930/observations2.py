"""OI-245 第二段观测（preregister.md「数据」「二、水平守卫候选」）。

在第一段口径上另取月末状态行的送转因子、累计现金与状态 V，并挂估值带的 ev_ps、net_debt_ps、λ／w／v 与行业门类；
逐行复现 `状态 V = 带 V ÷ 送转因子 − 累计现金`（相对差 < 1e-4，不符剔除），再按四个水平守卫候选近似重估 `P/V'`。

    python3 observations2.py     # → observations2.csv、observations2_check.json
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
sys.path.insert(0, str(EXP.parent / 'exp_oi245_20260930'))
import observations as obs1  # noqa: E402

CANDIDATES = (('LG1.3', 1.3, False), ('LG1.6', 1.6, False), ('LG2.0', 2.0, False), ('LGλ1.3', 1.3, True))
RAMP = 0.6
GATES = (('农', 'A'), ('林', 'A'), ('牧', 'A'), ('渔', 'A'), ('采矿', 'B'), ('制造', 'C'), ('纺织', 'C'), ('电力', 'D'),
         ('燃气', 'D'), ('水电煤', 'D'), ('建筑', 'E'), ('批发', 'F'), ('零售', 'F'), ('运输', 'G'), ('仓储', 'G'),
         ('住宿', 'H'), ('餐饮', 'H'), ('信息', 'I'), ('软件', 'I'), ('金融', 'J'), ('房地产', 'K'), ('租赁', 'L'),
         ('商务', 'L'), ('科研', 'M'), ('科学研究', 'M'), ('技术服务', 'M'), ('水利', 'N'), ('环境', 'N'), ('公共', 'N'),
         ('居民服务', 'O'), ('教育', 'P'), ('卫生', 'Q'), ('社会工作', 'Q'), ('文化', 'R'), ('体育', 'R'), ('娱乐', 'R'),
         ('综合', 'S'))


def gate(label: str) -> str:
    """证监会门类字母（同 `../exp_oi213_20260928/fairness.py`）。"""
    label = (label or '').strip()
    if len(label) > 2 and label[0].isascii() and label[0].isalpha() and label[1] == ' ':
        return label[0]
    for key, letter in GATES:
        if key in label:
            return letter
    return 'NA'


def industries():
    out, names = {}, {}
    with (ROOT / 'data/raw/a_share_securities.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            c = r['security_code'].zfill(6)
            out[c] = gate(r.get('industry'))
            names[c] = r['security_name']
    with (ROOT / 'data/processed/a_share_company_analysis_index.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            c = r['security_code'].zfill(6)
            names.setdefault(c, r['security_name'])
            if gate(r.get('industry')) != 'NA':
                out[c] = gate(r.get('industry'))
    return out, names


def month_ends(codes):
    out = {}
    with obs1.STATES.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        idx = [h.index(k) for k in ('security_code', 'date', 'valuation_ratio', 'band_report_date', 'band_available_at',
                                    'split_factor', 'cash_adjustment', 'intrinsic_value')]
        ic, idt = idx[0], idx[1]
        for row in reader:
            code = row[ic]
            if code not in codes or row[idt] < obs1.START:
                continue
            key = (code, row[idt][:7])
            prev = out.get(key)
            if prev is None or row[idt] > prev[0]:
                out[key] = tuple(row[i] for i in idx[1:])
    return out


def load_bands(codes):
    rows, annual = {}, defaultdict(list)
    keep = ('roic_path', 'nopat_ps', 'shares_est', 'net_debt_ps', 'intrinsic_value', 'growth_trust', 'peak_weight',
            'trough_weight', 'roic_nopat_mode')
    with obs1.BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            code = r['security_code']
            if code not in codes:
                continue
            rows[(code, r['report_date'], r['available_at'])] = {k: r.get(k, '') for k in keep}
            if r['status'] == 'ok' and r['report_date'].endswith('-12-31') and len(r['available_at']) == 10:
                nopat, shares = obs1.num(r['nopat_ps']), obs1.num(r['shares_est'])
                annual[code].append(dict(fy=int(r['report_date'][:4]), av=r['available_at'],
                                         nopat=nopat * shares if nopat is not None and shares else None, np=None))
    return rows, annual


def guard(base, m5, lam, t, only_trusted):
    """水平守卫：返回 (w_L, 基数')。"""
    if base is None or m5 is None or base <= 0 or m5 <= 0 or (only_trusted and not (lam and lam > 0)):
        return 0.0, base
    w = min(1.0, max(0.0, (base / m5 - t) / RAMP))
    return w, (1 - w) * base + w * m5


def candidate_values(band, base, m5, lam, factor, cash):
    """各候选的状态 V'（近似：企业价值按基数等比例缩放）。"""
    v_band = obs1.num(band['intrinsic_value'])
    nd = obs1.num(band['net_debt_ps']) or 0.0
    out = {}
    for name, t, only in CANDIDATES:
        w, base2 = guard(base, m5, lam, t, only)
        if w == 0.0:
            out[name] = (0.0, None)
            continue
        v2_band = (v_band + nd) * base2 / base - nd
        v2_state = v2_band / factor - cash
        out[name] = (w, v2_state if v2_state > 0 else float('nan'))
    return out


def main():
    nonfin = obs1.load_nonfin()
    codes = {c for c, _ in nonfin}
    ends = month_ends(codes)
    bands, annual = load_bands(codes)
    gates, names = industries()
    check = dict(nonfin_rows=len(nonfin), matched=0, pv_mismatch=0, v_identity_mismatch=0, other_path=0, written=0,
                 changed={name: 0 for name, *_ in CANDIDATES}, nonpositive={name: 0 for name, *_ in CANDIDATES})
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
        factor, cash, v_state = obs1.num(factor_s) or 1.0, obs1.num(cash_s) or 0.0, obs1.num(v_s)
        v_band = obs1.num(band['intrinsic_value'])
        if v_state is None or v_band is None or abs((v_band / factor - cash) / v_state - 1.0) > 1e-4:
            check['v_identity_mismatch'] += 1
            continue
        nopat, shares = obs1.num(band['nopat_ps']), obs1.num(band['shares_est'])
        base = nopat * shares if nopat is not None and shares else None
        fy = int(rp[:4])
        hist = obs1.history(annual.get(key[0], []), fy, av, 5)
        prior = [a['nopat'] for a in hist if a['nopat'] is not None]
        m5 = statistics.median(prior) if len(prior) >= 3 else None
        prev = hist[-1]['nopat'] if hist and hist[-1]['fy'] == fy - 1 else None
        lg = lambda a, b: obs1.clip(math.log(a / b), -1.0, 1.0) if a and b and a > 0 and b > 0 else None
        lam = obs1.num(band['growth_trust'])
        row = dict(code=key[0], name=names.get(key[0], ''), gate=gates.get(key[0], 'NA'), month=key[1], date=day, panel=panel,
                   pv=pv, f3=f3, f5=f5, path=band['roic_path'], mode=band['roic_nopat_mode'], lam=lam,
                   w=obs1.num(band['peak_weight']), v=obs1.num(band['trough_weight']),
                   F1=lg(base, m5), f1_recent=lg(base, prev), f1_old=lg(prev, m5), base=base, m5=m5)
        for name, (w, v2) in candidate_values(band, base, m5, lam, factor, cash).items():
            row[f'w_{name}'] = w
            if w == 0.0:
                row[f'pv_{name}'] = pv
            elif v2 != v2:
                row[f'pv_{name}'] = None
                check['nonpositive'][name] += 1
            else:
                row[f'pv_{name}'] = pv * v_state / v2
                check['changed'][name] += 1
        out.append(row)
    check['written'] = len(out)
    with (EXP / 'observations2.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    (EXP / 'observations2_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')
    print(check, flush=True)


if __name__ == '__main__':
    main()
