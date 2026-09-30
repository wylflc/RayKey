"""OI-249 观测（preregister.md「数据与方法」）：OI-245 第一段口径的月末行 × 各臂重建带（精确 V'）。

逐行核对：状态 `P/V` 与观测一致（相对差 < 1e-4）、`状态 V = 带 V ÷ 送转因子 − 累计现金`、对照重建（ctrl）与生产带
`intrinsic_value` 相同；不符的行剔除并计数。各臂 `状态 V' = 带 V' ÷ 送转因子 − 累计现金`，`P/V' = P/V × 状态 V ÷ 状态 V'`。

    python3 observations4.py      # → observations4.csv、observations4_check.json
"""
import csv
import json
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(EXP.parent / 'exp_oi245_20260930'))
sys.path.insert(0, str(EXP.parent / 'exp_oi245b_20260930'))
sys.path.insert(0, str(EXP))
import observations as obs1  # noqa: E402
import observations2 as ob2  # noqa: E402
from build import VARIANTS  # noqa: E402
from patch_builder import COMMODITY  # noqa: E402

NEW = [v for v in VARIANTS if v != 'ctrl']


def load_bands(path, codes=None):
    out = {}
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            if codes is None or r['security_code'] in codes:
                out[(r['security_code'], r['report_date'], r['available_at'])] = r
    return out


def industries():
    out = {}
    with (ROOT / 'data/reference/a_share_csrc_industry.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            em = (r.get('em2016') or '').strip()
            out[r['security_code']] = (em, any(em == p or em.startswith(p + '-') for p in COMMODITY))
    return out


def main():
    nonfin = obs1.load_nonfin()
    keys = sorted(k for k, (panel, pv, f3, _f5) in nonfin.items() if panel and f3 is not None)
    codes = {c for c, _ in keys}
    ends = ob2.month_ends(codes)
    prod = load_bands(obs1.BANDS, codes)
    bands = {v: load_bands(EXP / f'bands_{v}.csv', codes) for v in VARIANTS}
    ind = industries()
    num = obs1.num
    check = dict(sample_keys=len(keys), matched=0, no_state=0, pv_mismatch=0, other_path=0, v_identity_mismatch=0, ctrl_mismatch=0,
                 written=0, changed={v: 0 for v in NEW}, missing={v: 0 for v in NEW}, nonpositive={v: 0 for v in NEW})
    out = []
    for key in keys:
        panel, pv, f3, f5 = nonfin[key]
        rec = ends.get(key)
        if rec is None:
            check['no_state'] += 1
            continue
        day, pv_s, rp, av, factor_s, cash_s, v_s = rec
        if not pv_s or abs(float(pv_s) / pv - 1.0) > 1e-4:
            check['pv_mismatch'] += 1
            continue
        check['matched'] += 1
        bkey = (key[0], rp, av)
        band = prod.get(bkey)
        if band is None or band['roic_path'] not in obs1.PATHS:
            check['other_path'] += 1
            continue
        factor, cash, v_state = num(factor_s) or 1.0, num(cash_s) or 0.0, num(v_s)
        v_band = num(band['intrinsic_value'])
        if v_state is None or v_band is None or abs((v_band / factor - cash) / v_state - 1.0) > 1e-4:
            check['v_identity_mismatch'] += 1
            continue
        ctrl = bands['ctrl'].get(bkey)
        if ctrl is None or ctrl['intrinsic_value'] != band['intrinsic_value']:
            check['ctrl_mismatch'] += 1
            continue
        em, commodity = ind.get(key[0], ('', False))
        row = dict(code=key[0], month=key[1], date=day, panel=panel, pv=pv, f3=f3, report_date=rp, available_at=av,
                   path=band['roic_path'], mode=band['roic_nopat_mode'], w=num(band['peak_weight']) or 0.0,
                   v=num(band['trough_weight']) or 0.0, lam=num(band['growth_trust']), roic0=num(band['roic0']), em2016=em,
                   commodity=commodity)
        for vn in NEW:
            b = bands[vn].get(bkey)
            v2b = num(b['intrinsic_value']) if b and b['status'] == 'ok' else None
            if v2b is None:
                row[f'pv_{vn}'] = None
                check['missing'][vn] += 1
                continue
            if abs(v2b - v_band) <= 1e-12 * abs(v_band):          # 带值未变：沿用原 P/V（同第二、三段，避免状态 V 四位小数的舍入噪声）
                row[f'pv_{vn}'] = pv
                row[f'w_{vn}'] = num(b['peak_weight']) or 0.0
                row[f'roic0_{vn}'] = num(b['roic0'])
                continue
            v2 = v2b / factor - cash
            if v2 <= 0:
                row[f'pv_{vn}'] = None
                check['nonpositive'][vn] += 1
                continue
            row[f'pv_{vn}'] = pv * v_state / v2
            row[f'w_{vn}'] = num(b['peak_weight']) or 0.0
            row[f'roic0_{vn}'] = num(b['roic0'])
            check['changed'][vn] += 1
        out.append(row)
    check['written'] = len(out)
    fields = list(dict.fromkeys(k for r in out for k in r))
    with (EXP / 'observations4.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    (EXP / 'observations4_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps(check, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
