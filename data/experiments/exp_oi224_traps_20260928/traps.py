"""OI-224 第一步：便宜陷阱能否事前识别（preregister.md 读数 T1～T5）。

    python3 traps.py features   # → cache/features.csv：答案卷 v1 每个在册股票月一行（标签、买入区、15 个时点特征）
    python3 traps.py readings   # → results.json、report.md
"""
import bisect
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))

LABELS = ROOT / 'data/backtest/opportunity_trap_labels_v1.csv'
CASES = ROOT / 'data/reference/opportunity_trap_cases.csv'
STATES = Path(os.environ.get('TRAP_STATES', ROOT / 'data/experiments/exp_oi205b_20260928/states/CONTROL_build/a_share_daily_states_adopted.csv'))
F10 = ROOT / 'data/archive/pit-judgment-2026-08/f10_org_profile.json'
VERDICTS = {y: ROOT / f'data/archive/pit-judgment-2026-08/verdicts_{y}.csv' for y in (2010, 2015, 2020)}
STMT = ROOT / 'data/raw/financials_statements'
LINE = 1.0670
OPP, TRAP = '机会', '陷阱'
# 预定方向：+1 = 值越大越像陷阱，−1 = 值越小越像陷阱
FEATURES = dict(M1=-1, M2=+1, M3=-1, M4=-1, I1=-1, I2=-1, I3=-1, E1=-1, E2=-1, E3=+1, E4=+1, E5=+1, E6=+1, E7=+1, E8=+1)
PERIODS = (('2007–2012', '2007-01', '2012-12'), ('2013–2017', '2013-01', '2017-12'), ('2018 起', '2018-01', '9999-12'))
BOOT = 1000
SEED = 20260928


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- features

def load_statement_rows(codes: set[str]) -> dict:
    """{代码: {年报期: {字段}}}：资产负债表与利润表的年报行，公告日按法定截止封顶（不取重述前版本，见局限）。"""
    from disclosure_dates import available_at
    want = {'balance': ('CONTRACT_LIAB', 'ADVANCE_RECEIVABLES', 'ACCOUNTS_RECE', 'NOTE_RECE', 'NOTE_ACCOUNTS_RECE', 'FINANCE_RECE', 'INVENTORY'),
            'income': ('TOTAL_OPERATE_INCOME',)}
    out = defaultdict(lambda: defaultdict(dict))
    for kind, fields in want.items():
        with (STMT / f'{kind}.csv').open(encoding='utf-8', newline='') as f:
            for r in csv.DictReader(f):
                code = (r.get('SECURITY_CODE') or '').zfill(6)
                period = (r.get('REPORT_DATE') or '')[:10]
                notice = (r.get('NOTICE_DATE') or '')[:10]
                if code not in codes or not period.endswith('12-31') or not notice:
                    continue
                row = out[code][period]
                row['notice'] = max(row.get('notice', ''), available_at(period, notice))
                for k in fields:
                    row[k] = num(r.get(k))
    return out


def growth(a, b):
    return a / b - 1 if a is not None and b is not None and b > 0 else None


def industry_growth(series_all: dict, industry: dict) -> dict:
    """{(大类, 财年 Y): Y−5→Y 同一批公司年报营收合计的年化增速}。"""
    rev = defaultdict(dict)
    for code, series in series_all.items():
        ind = industry.get(code)
        if not ind:
            continue
        for period, row in series.items():
            if period.endswith('12-31'):
                v = num(row.get('total_operate_income'))
                if v is not None and v > 0:
                    rev[ind].setdefault(int(period[:4]), {})[code] = v
    out = {}
    for ind, years in rev.items():
        for y in years:
            if y - 5 in years:
                common = years[y].keys() & years[y - 5].keys()
                if len(common) >= 3:
                    a, b = sum(years[y][c] for c in common), sum(years[y - 5][c] for c in common)
                    out[(ind, y)] = (a / b) ** 0.2 - 1 if a > 0 and b > 0 else None
    return out


def features():
    import build_historical_valuation_bands as bhv
    import roic_inputs
    from divspread_names import is_divspread_financial
    from opportunity_trap_audit import load_pv
    rows = []
    with LABELS.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['panel'] == 'True' and r['label']:
                rows.append(r)
    test = set(filter(None, os.environ.get('TRAP_TEST_CODES', '').split(',')))   # 冒烟：只算这几只，行业宇宙同限
    if test:
        rows = [r for r in rows if r['code'] in test]
    codes = {r['code'] for r in rows}
    profile = json.loads(F10.read_text())
    industry = {c: (v.get('INDUSTRYCSRC1') or '').strip() for c, v in profile.items()
                if (v.get('INDUSTRYCSRC1') or '').strip() and (not test or c in test)}
    pv = load_pv(STATES, {(r['code'], r['date']) for r in rows})
    print('P/V', len(pv), flush=True)
    series_all = bhv.load_financials(codes | set(industry), notice_cap=True)
    ind_growth = industry_growth(series_all, industry)
    print('行业增速', len(ind_growth), flush=True)
    years = roic_inputs.load_statements(codes, roic_inputs.STMT_DIR, ic_floor=0.1, caliber='nonop', notice_cap=True,
                                        restricted_cash='notes_wc')
    raw = load_statement_rows(codes)
    verdicts = {}
    for y, path in VERDICTS.items():
        with path.open(encoding='utf-8-sig', newline='') as f:
            verdicts[y] = {r['security_code'].zfill(6): r['verdict'] for r in csv.DictReader(f)}
    names = {}
    out = []
    for r in rows:
        code, day = r['code'], r['date']
        names[code] = r['name']
        rec = dict(code=code, name=r['name'], month=r['month'], date=day, label=r['label'], f3=r['f3'],
                   financial=is_divspread_financial(code, r['name']), pv=pv.get((code, day)))
        rec['zone'] = rec['pv'] is not None and rec['pv'] <= LINE
        # ---- 逐季面板（时点版本、公告日 ≤ 观测日）----
        s = {p: row for p, row in bhv.series_as_of(series_all.get(code, {}), day).items() if (row.get('notice_date') or '9999') <= day}
        periods = sorted(s)
        latest = periods[-1] if periods else None
        annual = [p for p in periods if p.endswith('12-31')]
        def ttm_at(period, field):
            v = bhv.ttm(s, period, field) if period else None
            return v.value if v else None
        def shift(period, years_back):
            return f'{int(period[:4]) - years_back}{period[4:]}' if period else None
        np_now, np_prev = ttm_at(latest, 'parent_netprofit'), ttm_at(shift(latest, 1), 'parent_netprofit')
        rec['E8'] = (np_now - np_prev) / abs(np_prev) if np_now is not None and np_prev not in (None, 0) else None
        rev_now, rev_5 = ttm_at(latest, 'total_operate_income'), ttm_at(shift(latest, 5), 'total_operate_income')
        rec['I2'] = (rev_now / rev_5) ** 0.2 - 1 if rev_now and rev_5 and rev_now > 0 and rev_5 > 0 else None
        roes = [num(s[p].get('weightavg_roe')) for p in annual[-10:]]
        roes = [x / 100 for x in roes if x is not None]
        roe_now = bhv.roe_ttm(s, latest) if latest else None
        med = statistics.median(roes) if len(roes) >= 5 else None
        rec['E6'] = roe_now.value / med if roe_now and med and med > 0 else None
        gms = [num(s[p].get('gross_margin')) for p in annual]
        gms = [x for x in gms if x is not None]
        rec['M3'] = statistics.median(gms[-5:]) if len(gms) >= 3 else None
        rec['E7'] = gms[-1] - statistics.median(gms[-6:-1]) if len(gms) >= 4 else None
        # ---- 行业大类增速：观测日已过法定截止（次年 4-30）的最近财年 ----
        fy = int(day[:4]) - (1 if day[5:] > '04-30' else 2)
        ind = industry.get(code)
        rec['industry'] = ind or ''
        rec['I1'] = ind_growth.get((ind, fy)) if ind else None
        rec['I3'] = rec['I2'] - rec['I1'] if rec['I2'] is not None and rec['I1'] is not None else None
        # ---- 三大报表（ROIC 口径年报）----
        ys = sorted(roic_inputs.years_before(years.get(code, {}), day, 11), key=lambda y: y.period)
        rois = [roic_inputs.roic_of(y, prev) for prev, y in zip([None] + ys[:-1], ys)][-10:]
        rois = [x for x in rois if x is not None]
        rec['M1'] = statistics.median(rois) if len(rois) >= 5 else None
        mean = sum(rois) / len(rois) if rois else None
        rec['M2'] = statistics.pstdev(rois) / mean if len(rois) >= 5 and mean and mean > 0 else None
        last3 = ys[-3:]
        cfo = [y.cfo for y in last3 if y.cfo is not None]
        npf = [y.parent_netprofit for y in last3 if y.parent_netprofit is not None]
        rec['E1'] = sum(cfo) / sum(npf) if len(last3) == 3 and len(cfo) == 3 and len(npf) == 3 and sum(npf) > 0 else None
        da = sum(y.dep_amort for y in last3)
        rec['E5'] = sum(y.capex for y in last3) / da if len(last3) == 3 and da > 0 else None
        # ---- 资产负债表逐项（最新两个已可得年报）----
        avail = sorted(p for p, v in raw.get(code, {}).items() if v.get('notice', '9999') <= day)
        rec['E2'] = rec['E3'] = rec['E4'] = None
        if len(avail) >= 2 and int(avail[-1][:4]) - int(avail[-2][:4]) == 1:
            a, b = raw[code][avail[-1]], raw[code][avail[-2]]
            rev_a, rev_b = a.get('TOTAL_OPERATE_INCOME'), b.get('TOTAL_OPERATE_INCOME')
            adv = lambda x: (x.get('CONTRACT_LIAB') or 0.0) + (x.get('ADVANCE_RECEIVABLES') or 0.0)
            rec_ = lambda x: ((x.get('NOTE_ACCOUNTS_RECE') if x.get('NOTE_ACCOUNTS_RECE') is not None
                               else (x.get('ACCOUNTS_RECE') or 0.0) + (x.get('NOTE_RECE') or 0.0)) + (x.get('FINANCE_RECE') or 0.0))
            if rev_a and rev_a > 0:
                rec['E2'] = (adv(a) - adv(b)) / rev_a
            g_rev = growth(rev_a, rev_b)
            if g_rev is not None:
                g_rec, g_inv = growth(rec_(a), rec_(b)), growth(a.get('INVENTORY'), b.get('INVENTORY'))
                rec['E3'] = g_rec - g_rev if g_rec is not None else None
                rec['E4'] = g_inv - g_rev if g_inv is not None else None
        # ---- 时点护城河判定 ----
        snap = max((y for y in VERDICTS if y <= int(day[:4])), default=None)
        rec['M4'] = (1.0 if verdicts[snap].get(code) == 'worth_attention' else 0.0) if snap else None
        out.append(rec)
    (EXP / 'cache').mkdir(exist_ok=True)
    with (EXP / 'cache/features.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    meta = dict(states=str(STATES), states_sha256=sha(STATES), labels_sha256=sha(LABELS), rows=len(out),
                zone=sum(r['zone'] for r in out), coverage={k: sum(r[k] is not None for r in out) for k in FEATURES},
                job_id=os.getenv('SLURM_JOB_ID'))
    (EXP / 'features_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(meta, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- readings

def load_features():
    rows = []
    with (EXP / 'cache/features.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            for k in FEATURES:
                r[k] = num(r[k])
            r['zone'] = r['zone'] == 'True'
            r['financial'] = r['financial'] == 'True'
            rows.append(r)
    return rows


def auc(pos, neg):
    """P(pos > neg) + 0.5 P(=)；秩和实现。"""
    if not len(pos) or not len(neg):
        return float('nan')
    from scipy.stats import rankdata
    ranks = rankdata(np.concatenate([pos, neg]))
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def cluster_draws(rows, rng, n=BOOT):
    stocks = sorted({r['code'] for r in rows})
    idx = {c: i for i, c in enumerate(stocks)}
    s = np.array([idx[r['code']] for r in rows])
    for _ in range(n):
        yield np.bincount(rng.integers(0, len(stocks), len(stocks)), minlength=len(stocks)).astype(float)[s]


def interval(v):
    a = np.asarray([x for x in v if x == x])
    return [float(np.percentile(a, 5)), float(np.percentile(a, 95))] if len(a) else [None, None]


def weighted_auc(score, trap, w):
    """整簇重抽的权重 = 重复次数：展开成重复样本求 AUC。"""
    rep = w.astype(int)
    keep = rep > 0
    sc, tr, rp = score[keep], trap[keep], rep[keep]
    pos, neg = np.repeat(sc[tr], rp[tr]), np.repeat(sc[~tr], rp[~tr])
    return auc(pos, neg)


def feature_readings(rows, key, sign, rng):
    sel = [r for r in rows if r[key] is not None]
    if len(sel) < 50:
        return dict(n=len(sel))
    x = np.array([r[key] for r in sel]) * sign                  # 按预定方向：越大越像陷阱
    trap = np.array([r['label'] == TRAP for r in sel])
    opp = np.array([r['label'] == OPP for r in sel])
    q = np.searchsorted(np.quantile(x, [0.2, 0.4, 0.6, 0.8]), x, side='right')   # 0 = 最不像，4 = 最像陷阱
    months = np.array([r['month'] for r in sel])
    base_trap, base_opp = trap.mean(), opp.mean()
    out = dict(n=len(sel), stocks=len({r['code'] for r in sel}), base_trap=float(base_trap), base_opp=float(base_opp),
               auc=auc(x[trap], x[~trap]), auc_vs_opp=auc(x[trap], x[opp]))
    out['periods'] = {name: auc(x[trap & (months >= a) & (months <= b)], x[~trap & (months >= a) & (months <= b)])
                      for name, a, b in PERIODS}
    boot = defaultdict(list)
    for w in cluster_draws(sel, rng):
        boot['auc'].append(weighted_auc(x, trap, w))
        tot_t, tot_o, tot = (w * trap).sum(), (w * opp).sum(), w.sum()
        for g in range(5):
            m = q == g
            n_g = (w * m).sum()
            boot[f'trap{g}'].append((w * m * trap).sum() / n_g / (tot_t / tot) if n_g and tot_t else float('nan'))
            boot[f'opp{g}'].append((w * m * opp).sum() / n_g / (tot_o / tot) if n_g and tot_o else float('nan'))
    out['auc_ci'] = interval(boot['auc'])
    out['quintiles'] = [dict(q=g + 1, n=int((q == g).sum()), trap_share=float(trap[q == g].mean()), opp_share=float(opp[q == g].mean()),
                             trap_lift=float(trap[q == g].mean() / base_trap) if base_trap else None,
                             trap_lift_ci=interval(boot[f'trap{g}']), opp_lift=float(opp[q == g].mean() / base_opp) if base_opp else None,
                             opp_lift_ci=interval(boot[f'opp{g}'])) for g in range(5)]
    worst = out['quintiles'][4]
    out['effective'] = bool(out['auc_ci'][0] is not None and out['auc_ci'][0] > 0.55
                            and all(v == v and v > 0.5 for v in out['periods'].values())
                            and worst['trap_lift'] is not None and worst['trap_lift'] >= 1.5 and worst['trap_lift_ci'][0] > 1.0
                            and worst['opp_lift'] is not None and worst['opp_lift'] <= 1.0)
    return out


def logistic(X, y, ridge=1.0, iters=50):
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ beta))
        g = X.T @ (y - p) - ridge * beta
        H = (X * (p * (1 - p))[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        beta += step
        if np.abs(step).max() < 1e-8:
            break
    return beta


def design(rows, keys, stats=None):
    cols, names = [], []
    if stats is None:
        stats = {}
        for k in keys:
            v = np.array([r[k] for r in rows if r[k] is not None])
            med = float(np.median(v)) if len(v) else 0.0
            sd = float(v.std()) if len(v) > 1 and v.std() > 0 else 1.0
            stats[k] = (med, float(v.mean()) if len(v) else 0.0, sd)
    for k in keys:
        med, mean, sd = stats[k]
        raw = np.array([r[k] if r[k] is not None else med for r in rows], float)
        cols.append(np.clip((raw - mean) / sd, -5, 5)); names.append(k)
        cols.append(np.array([r[k] is None for r in rows], float)); names.append(k + '_missing')
    X = np.column_stack([np.ones(len(rows))] + cols)
    return X, stats


def walk_forward(rows):
    keys = list(FEATURES)
    preds = []
    for year in range(2011, 2024):
        train = [r for r in rows if r['month'] <= f'{year - 4}-12']
        test = [r for r in rows if r['month'][:4] == str(year)]
        if len(train) < 200 or not test or not any(r['label'] == TRAP for r in train):
            continue
        Xtr, stats = design(train, keys)
        beta = logistic(Xtr, np.array([r['label'] == TRAP for r in train], float))
        Xte, _ = design(test, keys, stats)
        p = 1 / (1 + np.exp(-Xte @ beta))
        preds += [dict(r, score=float(s), test_year=year) for r, s in zip(test, p)]
    return preds


def readings():
    rows = load_features()
    rng = np.random.default_rng(SEED)
    main = [r for r in rows if r['zone'] and not r['financial']]
    allm = [r for r in rows if not r['financial']]
    res = dict(rows=len(rows), main=len(main), main_trap=sum(r['label'] == TRAP for r in main), main_opp=sum(r['label'] == OPP for r in main),
               features={}, features_all_months={})
    for k, sign in FEATURES.items():
        res['features'][k] = feature_readings(main, k, sign, rng)
        res['features_all_months'][k] = {kk: v for kk, v in feature_readings(allm, k, sign, rng).items() if kk in ('n', 'auc', 'periods', 'base_trap')}
        f = res['features'][k]
        print(k, 'n', f.get('n'), 'AUC %.3f %s' % (f.get('auc', float('nan')), f.get('auc_ci')), 'periods', f.get('periods'),
              'worst trap×%.2f opp×%.2f' % (f['quintiles'][4]['trap_lift'], f['quintiles'][4]['opp_lift']) if 'quintiles' in f else '',
              'EFFECTIVE' if f.get('effective') else '', flush=True)
    preds = walk_forward(main)
    if preds:
        for p in preds:
            p['SCORE'] = p['score']
        combo = feature_readings(preds, 'SCORE', +1, rng)
        combo['years'] = {}
        for y in sorted({p['test_year'] for p in preds}):
            sub = [p for p in preds if p['test_year'] == y]
            sc, tr = np.array([p['score'] for p in sub]), np.array([p['label'] == TRAP for p in sub])
            combo['years'][y] = dict(n=len(sub), traps=int(tr.sum()), auc=auc(sc[tr], sc[~tr]))
        res['combined'] = combo
        print('组合 AUC %.3f %s' % (combo['auc'], combo['auc_ci']), 'EFFECTIVE' if combo.get('effective') else '', flush=True)
    # T5 具名陷阱：区间内首次进买入区的月份
    with CASES.open(encoding='utf-8-sig', newline='') as f:
        cases = [c for c in csv.DictReader(f) if c['kind'] == TRAP]
    quint = {}
    for k, sign in FEATURES.items():
        v = np.array([r[k] for r in main if r[k] is not None]) * sign
        quint[k] = np.quantile(v, [0.2, 0.4, 0.6, 0.8]) if len(v) else None
    res['cases'] = []
    for c in cases:
        hit = [r for r in main if r['code'] == c['security_code'] and c['window_start'] <= r['month'] <= c['window_end']]
        if not hit:
            res['cases'].append(dict(case=c['case_id'], name=c['security_name'], zone=False))
            continue
        r = min(hit, key=lambda x: x['month'])
        entry = dict(case=c['case_id'], name=c['security_name'], month=r['month'], zone=True, features={})
        for k, sign in FEATURES.items():
            entry['features'][k] = dict(value=r[k], quintile=(int(np.searchsorted(quint[k], r[k] * sign, side='right')) + 1
                                                              if r[k] is not None and quint[k] is not None else None))
        entry['worst_quintile'] = [k for k, v in entry['features'].items() if v['quintile'] == 5]
        res['cases'].append(entry)
    (EXP / 'results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')


if __name__ == '__main__':
    {'features': features, 'readings': readings}[sys.argv[1]]()
