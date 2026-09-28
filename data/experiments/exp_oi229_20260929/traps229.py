"""OI-229：买入区陷阱识别（E1 之外）——preregister.md 读数 T1～T7。

    python3 traps229.py features   # → cache/features.csv：答案卷 v1 每个在册股票月一行（标签、买入区、10 个新特征与 E1）
    python3 traps229.py readings   # → results.json

读数函数（AUC、整簇自助、五分组、T3 判据、滚动 logistic）与 OI-224 第一步（exp_oi224_traps_20260928/traps.py）同式。
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
STATES = ROOT / 'data/processed/a_share_daily_states_adopted.csv'
F10 = ROOT / 'data/archive/pit-judgment-2026-08/f10_org_profile.json'
STMT = ROOT / 'data/raw/financials_statements'
LINE = 1.0034
OPP, TRAP = '机会', '陷阱'
# 预定方向：+1 = 值越大越像陷阱，−1 = 值越小越像陷阱
FEATURES = dict(C1=+1, C2=+1, C3=+1, K1=+1, K2=+1, K3=+1, D1=+1, D2=-1, D3=+1, S1=-1)
REFERENCE = dict(E1=-1)                  # 只作 T6 分层与参照
PERIODS = (('2007–2012', '2007-01', '2012-12'), ('2013–2017', '2013-01', '2017-12'), ('2018 起', '2018-01', '9999-12'))
CYCLICAL_TAGS = {'H周期', 'F资源'}
BOOT = 1000
SEED = 20260929
IND_MIN, WINDOW, WINDOW_MIN = 5, 40, 20      # 行业统计量：每季至少 5 家；位置取 40 个季度、至少 20 个有值
PEER_MIN = 3


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


def month_shift(month: str, k: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    t = y * 12 + (m - 1) + k
    return f'{t // 12:04d}-{t % 12 + 1:02d}'


# ---------------------------------------------------------------- 行业统计量（C1～C3）

def deadline(period: str) -> str:
    """季度 q 的法定截止日（§6.3 第 2 条同口径）。"""
    y, md = int(period[:4]), period[5:]
    return {'03-31': f'{y}-04-30', '06-30': f'{y}-08-31', '09-30': f'{y}-10-31', '12-31': f'{y + 1}-04-30'}[md]


def prior_same(period: str) -> str:
    return f'{int(period[:4]) - 1}{period[4:]}'


def ttm_gross_profit(series: dict, period: str):
    """TTM 毛利 = 本期累计毛利 + 上年年报毛利 − 上年同期累计毛利；累计毛利 = 累计毛利率 × 累计营收。"""
    def gp(p):
        row = series.get(p)
        if row is None:
            return None
        gm, rev = num(row.get('gross_margin')), num(row.get('total_operate_income'))
        return gm / 100 * rev if gm is not None and rev is not None else None
    cur = gp(period)
    if cur is None:
        return None
    if period.endswith('12-31'):
        return cur
    fy, same = gp(f'{int(period[:4]) - 1}-12-31'), gp(prior_same(period))
    return cur + fy - same if fy is not None and same is not None else None


def industry_stats(series_all: dict, industry: dict) -> dict:
    """{大类: {季度: (ROE TTM 中位, TTM 毛利率中位, TTM 营收同比中位)}}，每项至少 IND_MIN 家。"""
    import build_historical_valuation_bands as bhv
    vals = defaultdict(lambda: defaultdict(lambda: ([], [], [])))
    for code, series in series_all.items():
        ind = industry.get(code)
        if not ind:
            continue
        for period in series:
            if period[5:] not in ('03-31', '06-30', '09-30', '12-31'):
                continue
            bucket = vals[ind][period]
            roe = bhv.roe_ttm(series, period)
            if roe is not None and roe.value is not None and math.isfinite(roe.value):
                bucket[0].append(roe.value)
            rev = bhv.ttm(series, period, 'total_operate_income')
            gp = ttm_gross_profit(series, period)
            if rev is not None and rev.value and rev.value > 0 and gp is not None:
                bucket[1].append(gp / rev.value)
            prev = bhv.ttm(series, prior_same(period), 'total_operate_income')
            if rev is not None and prev is not None and rev.value is not None and prev.value and prev.value > 0:
                bucket[2].append(rev.value / prev.value - 1)
    out = {}
    for ind, periods in vals.items():
        out[ind] = {p: tuple(statistics.median(v) if len(v) >= IND_MIN else None for v in lists)
                    for p, lists in periods.items()}
    return out


def position(stats: dict, day: str, k: int):
    """观测日可用的最近一季的统计量，在截至该季的 WINDOW 个季度中的分位（≤ 当季值的占比）。"""
    periods = sorted(p for p in stats if deadline(p) <= day)
    if not periods:
        return None
    cur = stats[periods[-1]][k]
    if cur is None:
        return None
    window = [stats[p][k] for p in periods[-WINDOW:] if stats[p][k] is not None]
    if len(window) < WINDOW_MIN:
        return None
    return sum(v <= cur for v in window) / len(window)


# ---------------------------------------------------------------- 年报逐项（K1）

def load_total_assets(codes: set[str]) -> dict:
    """{代码: {年报期: (可得日, 总资产)}}，公告日按法定截止封顶。"""
    from disclosure_dates import available_at
    out = defaultdict(dict)
    with (STMT / 'balance.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            code = (r.get('SECURITY_CODE') or '').zfill(6)
            period = (r.get('REPORT_DATE') or '')[:10]
            notice = (r.get('NOTICE_DATE') or '')[:10]
            if code not in codes or not period.endswith('12-31') or not notice:
                continue
            ta = num(r.get('TOTAL_ASSETS'))
            if ta is None:
                continue
            out[code][period] = (available_at(period, notice), ta)
    return out


# ---------------------------------------------------------------- 特征

def features():
    import build_historical_valuation_bands as bhv
    import roic_inputs
    from divspread_names import is_divspread_financial
    from moat_param_lab import total_return_index
    rows_all = list(csv.DictReader(LABELS.open(encoding='utf-8', newline='')))
    test = set(filter(None, os.environ.get('TRAP_TEST_CODES', '').split(',')))      # 冒烟：只算这几只
    rows = [r for r in rows_all if r['panel'] == 'True' and r['label'] and (not test or r['code'] in test)]
    codes = {r['code'] for r in rows}
    panel_rows = [r for r in rows_all if r['panel'] == 'True']            # D2 中位与 S1 同行：全部在册股票月（含无标签）
    panel_codes = {r['code'] for r in panel_rows}
    profile = json.loads(F10.read_text())
    industry = {c: (v.get('INDUSTRYCSRC1') or '').strip() for c, v in profile.items() if (v.get('INDUSTRYCSRC1') or '').strip()}
    ind_limit = os.environ.get('TRAP_IND_LIMIT')                          # 冒烟：行业宇宙只取测试股的同行前 N 家
    if test and ind_limit:
        keep = {industry.get(c) for c in test}
        peers = sorted(c for c, i in industry.items() if i in keep)[:int(ind_limit)]
        industry = {c: industry[c] for c in set(peers) | (test & set(industry))}
    # ---- P/V：在册股票月的月末日，以及 12 个月前同一股票的月末日 ----
    from opportunity_trap_audit import load_pv
    by_code_month = {(r['code'], r['month']): r['date'] for r in rows_all}
    want = {(r['code'], r['date']) for r in panel_rows}
    want |= {(r['code'], by_code_month[(r['code'], month_shift(r['month'], -12))]) for r in rows
             if (r['code'], month_shift(r['month'], -12)) in by_code_month}
    pv = load_pv(STATES, want)
    print('P/V', len(pv), flush=True)
    # ---- 总回报指数（答案卷同一实现）----
    actions = bhv.load_actions()
    tr_at = {}
    month_dates = defaultdict(list)
    for (c, m), d in by_code_month.items():
        month_dates[c].append((m, d))
    for code in sorted(panel_codes | codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        tr = total_return_index(prices, actions.get(code, []))
        for r_month, r_date in month_dates.get(code, ()):
            if r_date in tr:
                tr_at[(code, r_month)] = tr[r_date]
    print('总回报点', len(tr_at), flush=True)

    def ret12(code, month):
        a, b = tr_at.get((code, month)), tr_at.get((code, month_shift(month, -12)))
        return math.log(a / b) if a and b and a > 0 and b > 0 else None
    med_ret = {}
    by_month = defaultdict(list)
    for r in panel_rows:
        x = ret12(r['code'], r['month'])
        if x is not None:
            by_month[r['month']].append(x)
    med_ret = {m: statistics.median(v) for m, v in by_month.items() if v}
    # ---- S1 同行：同月在册、同大类、有 P/V 的其他公司 ----
    peers_pv = defaultdict(list)
    for r in panel_rows:
        v = pv.get((r['code'], r['date']))
        ind = industry.get(r['code'])
        if v is not None and ind:
            peers_pv[(ind, r['month'])].append((r['code'], v))
    # ---- 行业统计量（C1～C3）----
    series_all = bhv.load_financials(set(industry) | codes, notice_cap=True)
    stats = industry_stats(series_all, industry)
    print('行业统计量', len(stats), flush=True)
    # ---- 三大报表（估值池；K2 同行、K3、E1）----
    with (STMT / 'income.csv').open(encoding='utf-8', newline='') as f:        # 估值池即三大报表覆盖的公司
        pool_codes = {(r.get('SECURITY_CODE') or '').zfill(6) for r in csv.DictReader(f)}
    years = roic_inputs.load_statements(pool_codes, roic_inputs.STMT_DIR, ic_floor=0.1, caliber='nonop', notice_cap=True,
                                        restricted_cash='notes_wc')
    assets = load_total_assets(codes)
    pool_by_ind = defaultdict(list)
    for c in years:
        if industry.get(c):
            pool_by_ind[industry[c]].append(c)
    print('报表', len(years), '家', flush=True)
    out = []
    for r in rows:
        code, day, month = r['code'], r['date'], r['month']
        ind = industry.get(code) or ''
        rec = dict(code=code, name=r['name'], month=month, date=day, label=r['label'], tag=r['tag'], f3=r['f3'],
                   industry=ind, financial=is_divspread_financial(code, r['name']), pv=pv.get((code, day)))
        rec['zone'] = rec['pv'] is not None and rec['pv'] <= LINE
        # C1～C3
        for k, key in enumerate(('C1', 'C2', 'C3')):
            rec[key] = position(stats[ind], day, k) if ind in stats else None
        # K1：最新两个相邻已可得年报的总资产同比
        avail = sorted(p for p, (a, _) in assets.get(code, {}).items() if a <= day)
        rec['K1'] = None
        if len(avail) >= 2 and int(avail[-1][:4]) - int(avail[-2][:4]) == 1:
            ta_a, ta_b = assets[code][avail[-1]][1], assets[code][avail[-2]][1]
            rec['K1'] = ta_a / ta_b - 1 if ta_b > 0 else None
        # K2、K3、E1：ROIC 口径年报
        ys = sorted(roic_inputs.years_before(years.get(code, {}), day, 6), key=lambda y: y.period)
        last3, prev3 = ys[-3:], ys[-6:-3]
        cap_last, cap_prev = sum(y.capex for y in last3), sum(y.capex for y in prev3)
        rec['K3'] = cap_last / cap_prev if len(last3) == 3 and len(prev3) == 3 and cap_prev > 0 and cap_last >= 0 else None
        capex_sum = da_sum = 0.0
        n_peer = 0
        for c in pool_by_ind.get(ind, []):
            p3 = sorted(roic_inputs.years_before(years.get(c, {}), day, 3), key=lambda y: y.period)
            if len(p3) == 3 and sum(y.dep_amort for y in p3) > 0:
                capex_sum += sum(y.capex for y in p3)
                da_sum += sum(y.dep_amort for y in p3)
                n_peer += 1
        rec['K2'] = capex_sum / da_sum if n_peer >= PEER_MIN and da_sum > 0 else None
        cfo = [y.cfo for y in last3 if y.cfo is not None]
        npf = [y.parent_netprofit for y in last3 if y.parent_netprofit is not None]
        rec['E1'] = sum(cfo) / sum(npf) if len(last3) == 3 and len(cfo) == 3 and len(npf) == 3 and sum(npf) > 0 else None
        # D1～D3
        x = ret12(code, month)
        m12 = month_shift(month, -12)
        pv_then = pv.get((code, by_code_month.get((code, m12), '')))
        rec['D1'] = (x - math.log(rec['pv'] / pv_then)) if x is not None and rec['pv'] and pv_then else None
        rec['D2'] = x - med_ret[month] if x is not None and month in med_ret else None
        s = {p: row for p, row in bhv.series_as_of(series_all.get(code, {}), day).items() if (row.get('notice_date') or '9999') <= day}
        latest = max(s) if s else None
        e8 = None
        if latest:
            a, b = bhv.ttm(s, latest, 'parent_netprofit'), bhv.ttm(s, prior_same(latest), 'parent_netprofit')
            if a is not None and b is not None and a.value is not None and b.value not in (None, 0):
                e8 = (a.value - b.value) / abs(b.value)
        rec['D3'] = math.log(1 + min(max(e8, -0.9), 5.0)) - rec['D2'] if e8 is not None and rec['D2'] is not None else None
        # S1
        others = [v for c, v in peers_pv.get((ind, month), []) if c != code] if ind else []
        rec['S1'] = statistics.median(others) if len(others) >= PEER_MIN else None
        out.append(rec)
    (EXP / 'cache').mkdir(exist_ok=True)
    with (EXP / 'cache/features.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
    keys = list(FEATURES) + list(REFERENCE)
    meta = dict(states=str(STATES), states_sha256=sha(STATES), labels_sha256=sha(LABELS), line=LINE, rows=len(out),
                zone=sum(r['zone'] for r in out), zone_nonfin=sum(r['zone'] and not r['financial'] for r in out),
                coverage={k: sum(r[k] is not None for r in out) for k in keys},
                coverage_zone_nonfin={k: sum(r[k] is not None for r in out if r['zone'] and not r['financial']) for k in keys},
                job_id=os.getenv('SLURM_JOB_ID'))
    (EXP / 'features_meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps(meta, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- 读数（与 OI-224 同式）

def load_features():
    rows = []
    with (EXP / 'cache/features.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            for k in list(FEATURES) + list(REFERENCE):
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
    rep = w.astype(int)
    keep = rep > 0
    sc, tr, rp = score[keep], trap[keep], rep[keep]
    pos, neg = np.repeat(sc[tr], rp[tr]), np.repeat(sc[~tr], rp[~tr])
    return auc(pos, neg)


def feature_readings(rows, key, sign, rng, boot=True):
    sel = [r for r in rows if r[key] is not None]
    trap_n = sum(r['label'] == TRAP for r in sel)
    if len(sel) < 50 or trap_n < 5:
        return dict(n=len(sel), traps=trap_n)
    x = np.array([r[key] for r in sel]) * sign
    trap = np.array([r['label'] == TRAP for r in sel])
    opp = np.array([r['label'] == OPP for r in sel])
    q = np.searchsorted(np.quantile(x, [0.2, 0.4, 0.6, 0.8]), x, side='right')
    months = np.array([r['month'] for r in sel])
    base_trap, base_opp = trap.mean(), opp.mean()
    out = dict(n=len(sel), traps=int(trap.sum()), stocks=len({r['code'] for r in sel}), trap_stocks=len({r['code'] for r in sel if r['label'] == TRAP}),
               base_trap=float(base_trap), base_opp=float(base_opp), auc=auc(x[trap], x[~trap]), auc_vs_opp=auc(x[trap], x[opp]))
    out['periods'] = {name: auc(x[trap & (months >= a) & (months <= b)], x[~trap & (months >= a) & (months <= b)])
                      for name, a, b in PERIODS}
    if not boot:
        return out
    bs = defaultdict(list)
    for w in cluster_draws(sel, rng):
        bs['auc'].append(weighted_auc(x, trap, w))
        tot_t, tot_o, tot = (w * trap).sum(), (w * opp).sum(), w.sum()
        for g in range(5):
            m = q == g
            n_g = (w * m).sum()
            bs[f'trap{g}'].append((w * m * trap).sum() / n_g / (tot_t / tot) if n_g and tot_t else float('nan'))
            bs[f'opp{g}'].append((w * m * opp).sum() / n_g / (tot_o / tot) if n_g and tot_o else float('nan'))
    out['auc_ci'] = interval(bs['auc'])
    out['quintiles'] = [dict(q=g + 1, n=int((q == g).sum()), lo=float(np.min(x[q == g] * sign)) if (q == g).any() else None,
                             hi=float(np.max(x[q == g] * sign)) if (q == g).any() else None,
                             trap_share=float(trap[q == g].mean()), opp_share=float(opp[q == g].mean()),
                             trap_lift=float(trap[q == g].mean() / base_trap) if base_trap else None,
                             trap_lift_ci=interval(bs[f'trap{g}']), opp_lift=float(opp[q == g].mean() / base_opp) if base_opp else None,
                             opp_lift_ci=interval(bs[f'opp{g}'])) for g in range(5)]
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
    cols = []
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
        cols.append(np.clip((raw - mean) / sd, -5, 5))
        cols.append(np.array([r[k] is None for r in rows], float))
    return np.column_stack([np.ones(len(rows))] + cols), stats


def walk_forward(rows, keys):
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
    res = dict(rows=len(rows), main=len(main), main_stocks=len({r['code'] for r in main}),
               main_trap=sum(r['label'] == TRAP for r in main), main_opp=sum(r['label'] == OPP for r in main),
               features={}, features_all_months={}, beyond_e1={}, cyclical={})
    signs = {**FEATURES, **REFERENCE}
    for k, sign in signs.items():
        res['features'][k] = feature_readings(main, k, sign, rng)
        res['features_all_months'][k] = {kk: v for kk, v in feature_readings(allm, k, sign, rng, boot=False).items()
                                         if kk in ('n', 'auc', 'periods', 'base_trap')}
        f = res['features'][k]
        print(k, 'n', f.get('n'), 'AUC %.3f %s' % (f.get('auc', float('nan')), f.get('auc_ci')), 'periods', f.get('periods'),
              'worst trap×%.2f opp×%.2f' % (f['quintiles'][4]['trap_lift'], f['quintiles'][4]['opp_lift']) if 'quintiles' in f else '',
              'EFFECTIVE' if f.get('effective') else '', flush=True)
    # T6：E1 不在最差五分之一（或缺失）的子样本
    e1 = np.array([r['E1'] for r in main if r['E1'] is not None])
    cut = float(np.quantile(e1, 0.2))
    sub = [r for r in main if r['E1'] is None or r['E1'] >= cut]
    res['beyond_e1_cut'] = cut
    res['beyond_e1_n'] = len(sub)
    res['beyond_e1_traps'] = sum(r['label'] == TRAP for r in sub)
    for k, sign in FEATURES.items():
        f = feature_readings(sub, k, sign, rng)
        f['adds_beyond_e1'] = bool(res['features'][k].get('effective') and f.get('auc_ci') and f['auc_ci'][0] is not None
                                   and f['auc_ci'][0] > 0.5)
        res['beyond_e1'][k] = f
        print('T6', k, 'n', f.get('n'), 'AUC %.3f %s' % (f.get('auc', float('nan')), f.get('auc_ci')),
              'ADDS' if f['adds_beyond_e1'] else '', flush=True)
    # T7：周期类
    cyc = [r for r in main if r['tag'] in CYCLICAL_TAGS]
    res['cyclical_n'], res['cyclical_traps'] = len(cyc), sum(r['label'] == TRAP for r in cyc)
    for k, sign in FEATURES.items():
        res['cyclical'][k] = {kk: v for kk, v in feature_readings(cyc, k, sign, rng, boot=False).items()
                              if kk in ('n', 'traps', 'auc', 'auc_vs_opp', 'periods')}
    # T4：E1 + 10 个新特征，逐年滚动样本外
    preds = walk_forward(main, list(REFERENCE) + list(FEATURES))
    if preds:
        for p in preds:
            p['SCORE'] = p['score']
        combo = feature_readings(preds, 'SCORE', +1, rng)
        combo['years'] = {}
        for y in sorted({p['test_year'] for p in preds}):
            s_ = [p for p in preds if p['test_year'] == y]
            sc, tr = np.array([p['score'] for p in s_]), np.array([p['label'] == TRAP for p in s_])
            combo['years'][y] = dict(n=len(s_), traps=int(tr.sum()), auc=auc(sc[tr], sc[~tr]))
        res['combined'] = combo
        print('组合 AUC %.3f %s' % (combo['auc'], combo.get('auc_ci')), 'EFFECTIVE' if combo.get('effective') else '', flush=True)
    # T5：具名陷阱首次进买入区当月
    with CASES.open(encoding='utf-8-sig', newline='') as f:
        cases = [c for c in csv.DictReader(f) if c['kind'] == TRAP]
    quint = {}
    for k, sign in signs.items():
        v = np.array([r[k] for r in main if r[k] is not None]) * sign
        quint[k] = np.quantile(v, [0.2, 0.4, 0.6, 0.8]) if len(v) else None
    res['cases'] = []
    for c in cases:
        hit = [r for r in main if r['code'] == c['security_code'] and c['window_start'] <= r['month'] <= c['window_end']]
        if not hit:
            res['cases'].append(dict(case=c['case_id'], name=c['security_name'], zone=False))
            continue
        r = min(hit, key=lambda x: x['month'])
        entry = dict(case=c['case_id'], name=c['security_name'], month=r['month'], zone=True, zone_months=len(hit), features={})
        for k, sign in signs.items():
            entry['features'][k] = dict(value=r[k], quintile=(int(np.searchsorted(quint[k], r[k] * sign, side='right')) + 1
                                                              if r[k] is not None and quint[k] is not None else None))
        entry['worst_quintile'] = [k for k, v in entry['features'].items() if v['quintile'] == 5]
        res['cases'].append(entry)
    # 陷阱股逐只：买入区陷阱月数与各特征落在最差一组的月份占比
    by_stock = defaultdict(list)
    for r in main:
        if r['label'] == TRAP:
            by_stock[(r['code'], r['name'])].append(r)
    res['trap_stocks'] = []
    for (code, name), rs in sorted(by_stock.items(), key=lambda kv: -len(kv[1])):
        worst = {k: (sum(1 for r in rs if r[k] is not None and np.searchsorted(quint[k], r[k] * s, side='right') == 4)
                     / max(1, sum(r[k] is not None for r in rs))) for k, s in signs.items() if quint[k] is not None}
        res['trap_stocks'].append(dict(code=code, name=name, months=len(rs), first=rs[0]['month'], tag=rs[0]['tag'],
                                       worst_share={k: round(v, 3) for k, v in worst.items()}))
    (EXP / 'results.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + '\n')


if __name__ == '__main__':
    {'features': features, 'readings': readings}[sys.argv[1]]()
