"""OI-245 观测（preregister.md「数据」）：现行正式逐日状态的月末行 × 所挂估值带的三项特征，合并 OI-227 的前向回报与在册标记。

- 月末行：`data/processed/a_share_daily_states_adopted.csv` 每个（代码, 年月）的最后一行（2007-01 起），取 `P/V` 与带键
  （`band_report_date`、`band_available_at`）。
- 回报与在册：`../exp_oi227_20260928/nonfin_v4216.csv`（同口径月末 `P/V`），按（代码, 年月）合并，`P/V` 须一致（相对差 < 1e-4）。
- 特征：带键匹配 `data/processed/roic_bands.csv`，只取 growth／zero_growth 路径。特征列 F1／F2／F3 大写，与前向回报列 f3／f5 区分。

    python3 observations.py     # → observations.csv、observations_check.json
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
BANDS = ROOT / 'data/processed/roic_bands.csv'
NONFIN = ROOT / 'data/experiments/exp_oi227_20260928/nonfin_v4216.csv'
START = '2007-01-01'
PATHS = ('growth', 'zero_growth')


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clip(v, lo, hi):
    return None if v is None else max(lo, min(hi, v))


def load_nonfin():
    out = {}
    with NONFIN.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out[(r['code'], r['month'])] = (r['panel'] == 'True', float(r['pv']), num(r['f3']), num(r['f5']))
    return out


def month_ends(codes):
    out = {}
    with STATES.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, ipv, irp, iav = (h.index(k) for k in ('security_code', 'date', 'valuation_ratio', 'band_report_date', 'band_available_at'))
        for row in reader:
            code = row[ic]
            if code not in codes or row[idt] < START:
                continue
            key = (code, row[idt][:7])
            prev = out.get(key)
            if prev is None or row[idt] > prev[0]:
                out[key] = (row[idt], row[ipv], row[irp], row[iav])
    return out


def load_bands(codes):
    rows, annual = {}, defaultdict(list)
    keep = ('roic_path', 'nopat_ps', 'shares_est', 'v_zero_growth', 'intrinsic_value', 'net_debt_ps', 'wc_change',
            'wc_first_period', 'wc_last_period', 'eps_ttm', 'g0', 'roic_nopat_mode', 'status')
    with BANDS.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            code = r['security_code']
            if code not in codes:
                continue
            rec = {k: r.get(k, '') for k in keep}
            rows[(code, r['report_date'], r['available_at'])] = rec
            if r['status'] == 'ok' and r['report_date'].endswith('-12-31') and len(r['available_at']) == 10:
                nopat, shares, eps = num(r['nopat_ps']), num(r['shares_est']), num(r['eps_ttm'])
                annual[code].append(dict(fy=int(r['report_date'][:4]), av=r['available_at'],
                                         nopat=nopat * shares if nopat is not None and shares else None,
                                         np=eps * shares if eps is not None and shares else None))
    return rows, annual


def history(annual_rows, fy, av, years):
    """前 `years` 个财年（fy−years … fy−1）中可得日不晚于 av 的年报带，每个财年取最新可得的一行。"""
    best = {}
    for a in annual_rows:
        if fy - years <= a['fy'] <= fy - 1 and a['av'] <= av:
            if a['fy'] not in best or a['av'] > best[a['fy']]['av']:
                best[a['fy']] = a
    return [best[k] for k in sorted(best)]


def features(band, annual_rows, report_date, avail):
    nopat, shares = num(band['nopat_ps']), num(band['shares_est'])
    iv = num(band['intrinsic_value'])
    fy = int(report_date[:4])
    total = nopat * shares if nopat is not None and shares else None
    f1 = hist_median = None
    prior = [a['nopat'] for a in history(annual_rows, fy, avail, 5) if a['nopat'] is not None]
    if len(prior) >= 3:
        hist_median = statistics.median(prior)
        if total and total > 0 and hist_median > 0:
            f1 = clip(math.log(total / hist_median), -1.0, 1.0)
    cyc = None
    ten = [a['np'] for a in history(annual_rows, fy, avail, 10) if a['np'] is not None]
    if len(ten) >= 5:
        cyc, peak = 0, None
        for v in ten:
            if v <= 0 or (peak is not None and peak > 0 and v <= 0.5 * peak):
                cyc = 1
            peak = v if peak is None else max(peak, v)
    if band['roic_path'] == 'zero_growth':
        f2 = 0.0
    else:
        vz = num(band['v_zero_growth'])
        f2 = clip(1.0 - vz / iv, -1.0, 1.0) if vz is not None and iv and iv > 0 else None
    wc = num(band['wc_change'])
    years = None
    if band['wc_first_period'] and band['wc_last_period']:
        years = int(band['wc_last_period'][:4]) - int(band['wc_first_period'][:4])
    wc_abs = clip(wc / (years * total), -1.0, 1.0) if wc is not None and years and years > 0 and total and total > 0 else None
    nd = num(band['net_debt_ps'])
    f3 = clip(max(0.0, -nd) / iv, 0.0, 1.0) if nd is not None and iv and iv > 0 else None
    return dict(F1=f1, cyc=cyc, F2=f2, wc_absorb=wc_abs, F3=f3, nopat_total=total, nopat_hist_median=hist_median)


def main():
    nonfin = load_nonfin()
    codes = {c for c, _ in nonfin}
    ends = month_ends(codes)
    bands, annual = load_bands(codes)
    check = dict(nonfin_rows=len(nonfin), matched=0, pv_mismatch=0, no_state=0, no_band=0, other_path=0, written=0)
    out = []
    for key in sorted(nonfin):
        panel, pv, f3, f5 = nonfin[key]
        rec = ends.get(key)
        if rec is None:
            check['no_state'] += 1
            continue
        day, pv_s, rp, av = rec
        if not pv_s or abs(float(pv_s) / pv - 1.0) > 1e-4:
            check['pv_mismatch'] += 1
            continue
        check['matched'] += 1
        band = bands.get((key[0], rp, av))
        if band is None:
            check['no_band'] += 1
            continue
        if band['roic_path'] not in PATHS:
            check['other_path'] += 1
            continue
        feat = features(band, annual.get(key[0], []), rp, av)
        out.append(dict(code=key[0], month=key[1], date=day, panel=panel, pv=pv, f3=f3, f5=f5, path=band['roic_path'],
                        mode=band['roic_nopat_mode'], report_date=rp, available_at=av, **feat))
    check['written'] = len(out)
    with (EXP / 'observations.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    for k in ('F1', 'cyc', 'F2', 'wc_absorb', 'F3'):
        check[f'non_null_{k}'] = sum(r[k] is not None for r in out)
    (EXP / 'observations_check.json').write_text(json.dumps(check, ensure_ascii=False, indent=1) + '\n')
    print(check, flush=True)


if __name__ == '__main__':
    main()
