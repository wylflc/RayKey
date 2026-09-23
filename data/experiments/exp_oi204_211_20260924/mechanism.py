"""Mechanism checks for OI-204 (object of the excess-return fade) and OI-211 (negative invested capital).

M1  engine property on production growth bands: share valued below the zero-growth EV (NOPAT/WACC) although
    ROIC0 exceeds the terminal return, under the production book fade and under the new-capital fade.
M2  persistence of whole-book returns: realised 5-year median ROE/ROIC over t+1..t+5 and t+6..t+10 against the
    start median, as the share of the start excess over the terminal return that survives.  Book fade predicts
    0.7 and 0.2 (years 3 and 8 of a linear 10-year fade); the new-capital path is computed from the engine.
    a) full market, annual weighted ROE (terminal 12% = r + 2pp);  b) statement roster, production roic0 bands.
M3  realised NOPAT growth after firm-years with invested capital <= 0 (the zero-growth fallback assumes none).
M4  NOPAT growth and cash conversion over 5/10 years: realised vs each fade (linear book, new capital, exponential).
M5  λ of the exponential whole-book fade (rule registered before any backtest, preregister.md): weighted least squares
    of e^(−3λ) and e^(−8λ) on the M2b bucket medians above 20% ROIC0, weights = start counts; grid 0.001.

    python3 mechanism.py        # writes mechanism.json and mechanism.txt
"""
import csv
import glob
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from intrinsic_value import ValuationError, intrinsic_value  # noqa: E402
import roic_inputs  # noqa: E402

A_SHARE = ('000', '001', '002', '003', '300', '301', '600', '601', '603', '605', '688', '689')
BUCKETS = ((0.12, 0.20), (0.20, 0.30), (0.30, 0.40), (0.40, 0.80), (0.80, 99.0))
LINES = []


def out(line=''):
    LINES.append(line)
    print(line)


def med(xs):
    return statistics.median(xs) if xs else None


def bucket(x):
    return next(((f'{lo:.0%}–{hi:.0%}' if hi < 99 else f'>{lo:.0%}') for lo, hi in BUCKETS if lo < x <= hi), None)


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def book_return_path(roic0, g0, w, roic_t, consistent):
    """Whole-book return by year implied by the engine (NOPAT0 = 1): NOPAT_t / IC_{t-1}."""
    res = intrinsic_value(1.0, roic0, g0, w, roe_terminal=roic_t, consistent=consistent)
    if consistent:
        return list(res.roe_path)      # book fade: the faded return is the whole-book return by construction
    ic = 1.0 / roic0 + min(max(res.g_path[0] / roic0, 0.0), 1.0)   # year-0 retention funds g_1 (engine 修正四)
    path = []
    for eps, payout in zip(res.eps_path, res.payout_path):
        path.append(eps / ic)
        ic += eps * (1 - payout)
    return path


def m1(bands):
    out('## M1 增长路径低于零增长企业价值（生产带，ROIC0 > 终值回报）')
    rows = defaultdict(lambda: [0, 0, 0])
    for r in bands:
        roic0, w, rt, g0, nopat = (fnum(r[k]) for k in ('roic0', 'wacc', 'roe_terminal', 'g0', 'nopat_ps'))
        if r['roic_path'] != 'growth' or None in (roic0, w, rt, g0, nopat) or roic0 <= rt or nopat <= 0:
            continue
        zero = 1.0 / w
        try:
            book = intrinsic_value(1.0, roic0, g0, w, roe_terminal=rt).intrinsic_value
            new = intrinsic_value(1.0, roic0, g0, w, roe_terminal=rt, consistent=False).intrinsic_value
        except ValuationError:
            continue
        key = bucket(roic0) if roic0 > 0.12 else '≤12%'
        rows[key][0] += 1
        rows[key][1] += book < zero
        rows[key][2] += new < zero
    table = {}
    out('| ROIC0 | 带数 | 整本衰减低于零增长 | 新增资本衰减低于零增长 |')
    for key in ['≤12%'] + [bucket((lo + min(hi, 1.0)) / 2) for lo, hi in BUCKETS]:
        n, b, c = rows.get(key, [0, 0, 0])
        if n:
            out(f'| {key} | {n} | {b / n:.1%} | {c / n:.1%} |')
            table[key] = dict(bands=n, book_below_zero=b / n, new_capital_below_zero=c / n)
    return table


def annual_roe():
    """Full-market annual weighted ROE by code and year (A-share codes, first row per code)."""
    series = defaultdict(dict)
    for path in sorted(glob.glob(str(ROOT / 'data/raw/financials/*-12-31.csv'))):
        year = int(Path(path).name[:4])
        with open(path, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                code = r['security_code'].zfill(6)
                roe = fnum(r.get('weightavg_roe'))
                if code.startswith(A_SHARE) and roe is not None and year not in series[code]:
                    series[code][year] = roe / 100
    return series


def persistence(series, terminal, label, implied=None):
    out(f'## M2{label}')
    result, starts = {}, defaultdict(list)
    attrition = defaultdict(lambda: [0, 0, 0])
    for code, by_year in series.items():
        for t in by_year:
            window = [by_year[y] for y in range(t - 4, t + 1) if y in by_year]
            if len(window) < 4:
                continue
            start = med(window)
            if start is None or start <= terminal:
                continue
            key = bucket(start)
            if key is None:
                continue
            attrition[key][0] += 1
            for h, lo in ((5, 1), (10, 6)):
                if t + h > max(by_year):
                    continue
                later = [by_year[y] for y in range(t + lo, t + lo + 5) if y in by_year]
                if len(later) < 4:
                    attrition[key][1 if h == 5 else 2] += 1
                    continue
                starts[(key, h)].append(((med(later) - terminal) / (start - terminal), code, t))
    out('| 起点五年中位 | 起点数 | 公司数 | 第 1～5 年存续比中位 | P25～P75 | 第 6～10 年存续比中位 | P25～P75 | 整本衰减预测 | 新增资本衰减预测 |')
    for lo, hi in BUCKETS:
        key = bucket((lo + min(hi, 1.0)) / 2)
        cells = []
        for h in (5, 10):
            vals = sorted(v for v, _c, _t in starts[(key, h)])
            if not vals:
                cells.append(None)
                continue
            q = lambda f: vals[int(f * (len(vals) - 1))]
            cells.append(dict(n=len(vals), firms=len({c for _v, c, _t in starts[(key, h)]}), median=med(vals), p25=q(.25), p75=q(.75)))
        if not cells[0]:
            continue
        imp = implied.get(key) if implied else None
        c5, c10 = cells
        out(f"| {key} | {c5['n']} | {c5['firms']} | {c5['median']:.2f} | {c5['p25']:.2f}～{c5['p75']:.2f} | "
            + (f"{c10['median']:.2f} | {c10['p25']:.2f}～{c10['p75']:.2f}" if c10 else '— | —')
            + f" | 0.70／0.20 | {('%.2f／%.2f' % imp) if imp else '—'} |")
        result[key] = dict(first5=c5, next5=c10, attrition=attrition[key], new_capital_implied=imp)
    cohorts = {}
    out('')
    out('按起点年份分组的第 1～5 年存续比中位（同一起点五年中位分档）：')
    out('| 起点五年中位 | ≤2008 | 2009～2013 | 2014～2020 |')
    for lo, hi in BUCKETS:
        key = bucket((lo + min(hi, 1.0)) / 2)
        cells = []
        for a, b in ((0, 2008), (2009, 2013), (2014, 2020)):
            vals = [v for v, _c, t in starts[(key, 5)] if a <= t <= b]
            cells.append((med(vals), len(vals)))
        cohorts[key] = cells
        out(f"| {key} | " + ' | '.join(f'{m:.2f}（{n}）' if m is not None else '—' for m, n in cells) + ' |')
    return dict(buckets=result, cohorts=cohorts)


def roster_roic(bands):
    """Annual production roic0 by code/year (5-year normalised, point-in-time) and the engine inputs at t."""
    series, inputs = defaultdict(dict), {}
    for r in bands:
        if not r['report_date'].endswith('12-31') or r['status'] != 'ok':
            continue
        roic0 = fnum(r['roic0'])
        year = int(r['report_date'][:4])
        if roic0 is None:
            if r['roic_path'] == 'zero_growth':       # 投入资本各年 ≤ 0：回报无上界，按 +∞ 计入实现值（不删样本）
                series[r['security_code']][year] = float('inf')
            continue
        series[r['security_code']][year] = roic0
        if r['roic_path'] == 'growth':
            inputs[(r['security_code'], year)] = tuple(fnum(r[k]) for k in ('roic0', 'g0', 'wacc', 'roe_terminal'))
    return series, inputs


def roic_persistence(series, inputs):
    """roic0 is already a 5-year median, so compare roic0 at t with roic0 at t+5 and t+10 directly."""
    out('## M2b 生产 ROIC0（五年中位，报表名单，存活偏差见注）')
    groups = defaultdict(list)
    for code, by_year in series.items():
        for t, start in by_year.items():
            if (code, t) not in inputs or start == float('inf'):
                continue
            roic0, g0, w, rt = inputs[(code, t)]
            if None in (g0, w, rt) or start <= rt:
                continue
            key = bucket(start)
            if key is None:
                continue
            try:
                book = book_return_path(roic0, g0, w, rt, True)
                new = book_return_path(roic0, g0, w, rt, False)
            except ValuationError:
                continue
            ex = start - rt
            row = dict(code=code, t=t, pred_book=(med(book[:5]) - rt) / ex, pred_book10=(med(book[5:]) - rt) / ex,
                       pred_new=(med(new[:5]) - rt) / ex, pred_new10=(med(new[5:]) - rt) / ex)
            for h in (5, 10):
                later = by_year.get(t + h)
                row[f'real{h}'] = None if later is None else (later - rt) / ex
            groups[key].append(row)
    result = {}
    out('| ROIC0 | 起点数 | 公司数 | 实现 t+5 | 整本 | 新增 | 实现 t+10 | 整本 | 新增 | t+5 更接近新增资本的占比 |')
    for lo, hi in BUCKETS:
        key = bucket((lo + min(hi, 1.0)) / 2)
        rows = [r for r in groups.get(key, []) if r['real5'] is not None]
        if not rows:
            continue
        rows10 = [r for r in rows if r['real10'] is not None]
        closer = sum(abs(r['real5'] - r['pred_new']) < abs(r['real5'] - r['pred_book']) for r in rows) / len(rows)
        cells = dict(n=len(rows), firms=len({r['code'] for r in rows}), real5=med([r['real5'] for r in rows]),
                     book5=med([r['pred_book'] for r in rows]), new5=med([r['pred_new'] for r in rows]),
                     n10=len(rows10), real10=med([r['real10'] for r in rows10]),
                     book10=med([r['pred_book10'] for r in rows10]), new10=med([r['pred_new10'] for r in rows10]),
                     closer_new=closer)
        out(f"| {key} | {cells['n']} | {cells['firms']} | {cells['real5']:.2f} | {cells['book5']:.2f} | {cells['new5']:.2f} | "
            + (f"{cells['real10']:.2f} | {cells['book10']:.2f} | {cells['new10']:.2f}" if rows10 else '— | — | —')
            + f" | {closer:.0%} |")
        result[key] = cells
    return result


def cash_flow_paths(bands):
    """M4: which fade object better predicts the NOPAT growth and cash conversion that the valuation discounts.

    Model (NOPAT0 = 1): NOPAT growth year 1 → year h and FCFF/NOPAT summed over years 1..h.  Realised (statement
    totals): NOPAT_{t+h}/NOPAT_{t+1} and Σ(NOPAT − (capex − D&A) − ΔWC)/ΣNOPAT over t+1..t+h.  Totals include
    issuance and acquisitions; the roster is a surviving, moat-selected set, both of which bias realised values up."""
    out('## M4 现金流路径：NOPAT 增长与现金转化（报表名单）')
    years = roic_inputs.load_statements(caliber='nonop')
    annual = {c: {int(p[:4]): y for p, y in by.items() if p.endswith('12-31')} for c, by in years.items()}
    groups = defaultdict(list)
    for r in bands:
        if not r['report_date'].endswith('12-31') or r['roic_path'] != 'growth':
            continue
        roic0, g0, w, rt = (fnum(r[k]) for k in ('roic0', 'g0', 'wacc', 'roe_terminal'))
        if None in (roic0, g0, w, rt) or roic0 <= rt or bucket(roic0) is None:
            continue
        code, t = r['security_code'], int(r['report_date'][:4])
        by = annual.get(code, {})
        for h in (5, 10):
            span = [by.get(t + k) for k in range(0, h + 1)]
            if any(y is None or y.nopat is None or y.working_capital is None for y in span) or span[1].nopat <= 0:
                continue
            nopat = sum(y.nopat for y in span[1:])
            if nopat <= 0:
                continue
            fcff = sum(y.nopat - (y.capex - y.dep_amort) - (y.working_capital - prev.working_capital)
                       for prev, y in zip(span, span[1:]))
            try:
                paths = {k: intrinsic_value(1.0, roic0, g0, w, roe_terminal=rt, **kw) for k, kw in (
                    ('book', {}), ('new', dict(consistent=False)), ('exp', dict(roe_lam=LAMBDA[0], horizon=50)))}
            except ValuationError:
                continue
            row = dict(code=code, t=t, real_g=span[h].nopat / span[1].nopat, real_c=fcff / nopat)
            for k, res in paths.items():
                eps, pay = res.eps_path[:h], res.payout_path[:h]
                row[f'{k}_g'] = eps[-1] / eps[0]
                row[f'{k}_c'] = sum(e * q for e, q in zip(eps, pay)) / sum(eps)
            groups[(bucket(roic0), h)].append(row)
    result = {}
    for h in (5, 10):
        out(f'第 1～{h} 年：')
        out('| ROIC0 | 起点数 | 公司数 | NOPAT 倍数 实现 | 整本线性 | 新增 | 整本指数 | 现金转化 实现 | 整本线性 | 新增 | 整本指数 | 倍数更接近新增 | 转化更接近新增 |')
        for lo, hi in BUCKETS:
            key = bucket((lo + min(hi, 1.0)) / 2)
            rows = groups.get((key, h), [])
            if not rows:
                continue
            c = {f: med([x[f] for x in rows]) for f in ('real_g', 'book_g', 'new_g', 'exp_g', 'real_c', 'book_c', 'new_c', 'exp_c')}
            c['closer_g'] = sum(abs(x['real_g'] - x['new_g']) < abs(x['real_g'] - x['book_g']) for x in rows) / len(rows)
            c['closer_c'] = sum(abs(x['real_c'] - x['new_c']) < abs(x['real_c'] - x['book_c']) for x in rows) / len(rows)
            c['n'], c['firms'] = len(rows), len({x['code'] for x in rows})
            out(f"| {key} | {c['n']} | {c['firms']} | {c['real_g']:.2f} | {c['book_g']:.2f} | {c['new_g']:.2f} | {c['exp_g']:.2f} | "
                f"{c['real_c']:.2f} | {c['book_c']:.2f} | {c['new_c']:.2f} | {c['exp_c']:.2f} | {c['closer_g']:.0%} | {c['closer_c']:.0%} |")
            result[f'{key}|{h}'] = c
    return result


LAMBDA = [None]


def fit_lambda(m2b):
    import math
    out('## M5 指数整本衰减 λ（预登记规则：M2b 起点 ROIC0 > 20% 各档中位，按起点数加权最小二乘）')
    cells = [(v['n'], v['real5'], v['n10'], v['real10']) for k, v in m2b.items() if not k.startswith('12%')]
    def loss(lam):
        return sum(n5 * (math.exp(-3 * lam) - p5) ** 2 + (n10 * (math.exp(-8 * lam) - p10) ** 2 if p10 is not None else 0)
                   for n5, p5, n10, p10 in cells)
    grid = [i / 1000 for i in range(10, 501)]
    lam = min(grid, key=loss)
    out(f'λ = {lam:.3f}（e^(−3λ) = {math.exp(-3 * lam):.2f}、e^(−8λ) = {math.exp(-8 * lam):.2f}；各档实现见 M2b）')
    LAMBDA[0] = round(lam, 2)
    out(f'建带取两位小数 λ = {LAMBDA[0]:.2f}，回报路径 50 年（剩余超额 e^(−50λ) = {math.exp(-50 * LAMBDA[0]):.3%}）')
    return dict(lambda_fit=lam, lambda_used=LAMBDA[0])


def negative_ic():
    out('## M3 投入资本 ≤ 0 的财年之后的 NOPAT 增长（报表名单）')
    years = roic_inputs.load_statements(caliber='nonop')
    groups = defaultdict(list)
    for code, by_period in years.items():
        annual = {int(p[:4]): y for p, y in by_period.items() if p.endswith('12-31')}
        for t, y in annual.items():
            if y.is_financial or y.nopat is None or y.nopat <= 0 or y.total_equity is None or y.total_equity <= 0:
                continue
            later = annual.get(t + 3)
            if later is None or later.nopat is None or later.nopat <= 0:
                continue
            ic = y.interest_debt + y.total_equity - y.excess_cash
            groups['IC ≤ 0' if ic <= 0 else 'IC > 0'].append(((later.nopat / y.nopat) ** (1 / 3) - 1, code))
    result = {}
    out('| 组 | 财年数 | 公司数 | 其后三年 NOPAT 年化中位 | P25～P75 | 为正占比 |')
    for key in ('IC ≤ 0', 'IC > 0'):
        vals = sorted(v for v, _c in groups[key])
        q = lambda f: vals[int(f * (len(vals) - 1))]
        cells = dict(n=len(vals), firms=len({c for _v, c in groups[key]}), median=med(vals), p25=q(.25), p75=q(.75),
                     positive=sum(v > 0 for v in vals) / len(vals))
        out(f"| {key} | {cells['n']} | {cells['firms']} | {cells['median']:.1%} | {cells['p25']:.1%}～{cells['p75']:.1%} | {cells['positive']:.0%} |")
        result[key] = cells
    return result


def main():
    with open(ROOT / 'data/processed/roic_bands.csv', encoding='utf-8-sig') as f:
        bands = [r for r in csv.DictReader(f) if r['status'] == 'ok']
    report = dict(m1=m1(bands))
    implied = {}
    for lo, hi in BUCKETS:     # new-capital implied persistence at the bucket midpoint, r = 10%, g0 = 5%
        start = (lo + min(hi, 1.0)) / 2
        path = book_return_path(start, 0.05, 0.10, 0.12, False)
        implied[bucket(start)] = ((med(path[:5]) - 0.12) / (start - 0.12), (med(path[5:]) - 0.12) / (start - 0.12))
    report['m2a'] = persistence(annual_roe(), 0.12, 'a 全市场年度加权 ROE（终值回报 12%；新增资本预测取 g0 = 5%）', implied)
    series, inputs = roster_roic(bands)
    report['m2b'] = roic_persistence(series, inputs)
    report['m5'] = fit_lambda(report['m2b'])
    report['m3'] = negative_ic()
    report['m4'] = cash_flow_paths(bands)
    (EXP / 'mechanism.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (EXP / 'mechanism.txt').write_text('\n'.join(LINES) + '\n')


if __name__ == '__main__':
    main()
