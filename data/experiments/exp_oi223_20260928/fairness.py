"""OI-223 估值公允性检验（preregister.md 读数 1）：CONTROL（统一 r = 10%）与分档臂（环境变量 FAIR_ARM，缺省 TIERS）的月末 `P/V`
对其后 3／5 年含分红总回报。

口径同 `../exp_oi206_20260928/fairness.py`，两臂：`d = ln(PV_G / PV_C)`，`d < 0` 为降 r、V 升一侧（T1／T2，字段 dn），
`d > 0` 为升 r、V 降一侧（T4／T5 与年报不足 5 年者，字段 dp），两侧分开读。另按档、按账面杠杆组（OI-221 并入）做校准，
并报 2015 年起子样本（早年约半数公司因年报不足取 T4）。重抽整侧缺席时该次记为奇异、不进区间（`singular_draws`）。
两条路径都进样本（银行与保险除外）。

    python3 fairness.py              # → fairness.json、fairness_cases.csv；逐月观测写 cache/fairness_observations.csv
    EXP_TEST=1 python3 fairness.py   # 冒烟：面板子集状态、重抽 50 次，只写 cache/
"""
import bisect
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402
from moat_param_lab import forward_annualized, total_return_index  # noqa: E402

TEST = os.environ.get('EXP_TEST') == '1'
ARMS = ('C', 'G')
FAIR_ARM = os.environ.get('FAIR_ARM', 'TIERS')
BANDS = {'C': EXP / 'states/CONTROL_build', 'G': EXP / f'states/{FAIR_ARM}_build'}
STATES = {a: p / 'a_share_daily_states_adopted.csv' for a, p in BANDS.items()}
if TEST:
    STATES = {'C': EXP / 'states/CONTROL/a_share_daily_states_adopted.csv', 'G': EXP / 'states/G/a_share_daily_states_adopted.csv'}
OUT = EXP / 'cache' if TEST else EXP
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
FROZEN_ACTIONS = EXP / 'old_inputs/data/raw/corporate_actions/a_share_corporate_actions.csv'
START = '2007-01-01'
PV_RANGE = (0.2, 5.0)
NEUTRAL, DISPUTED = 0.02, 0.15
BOOT = 50 if TEST else 1000
HORIZONS = (3, 5)
NAMED = ('600519', '603288', '600436', '300750', '600585', '601088')   # 预登记具名：茅台、海天、片仔癀、宁德、海螺、神华
TIERS_FILE = EXP / 'discount_rate_tiers_pit.csv'
BUCKETS = ((0.2, 0.8), (0.8, 1.2), (1.2, 2.0), (2.0, 5.0))
GATES = (('农', 'A'), ('林', 'A'), ('牧', 'A'), ('渔', 'A'), ('采矿', 'B'), ('制造', 'C'), ('纺织', 'C'), ('电力', 'D'),
         ('燃气', 'D'), ('水电煤', 'D'), ('建筑', 'E'), ('批发', 'F'), ('零售', 'F'), ('运输', 'G'), ('仓储', 'G'),
         ('住宿', 'H'), ('餐饮', 'H'), ('信息', 'I'), ('软件', 'I'), ('金融', 'J'), ('房地产', 'K'), ('租赁', 'L'),
         ('商务', 'L'), ('科研', 'M'), ('科学研究', 'M'), ('技术服务', 'M'), ('水利', 'N'), ('环境', 'N'), ('公共', 'N'),
         ('居民服务', 'O'), ('教育', 'P'), ('卫生', 'Q'), ('社会工作', 'Q'), ('文化', 'R'), ('体育', 'R'), ('娱乐', 'R'),
         ('综合', 'S'))


def gate(label: str) -> str:
    label = (label or '').strip()
    if len(label) > 2 and label[0].isascii() and label[0].isalpha() and label[1] == ' ':
        return label[0]
    for key, letter in GATES:
        if key in label:
            return letter
    return 'NA'


def load_bands(folder: Path):
    """行键 → (ok, 路径)；逐票拒绝带的「可得日 → 已拒最新报告期」阶梯，用于判沿用旧带。"""
    info, rejected = {}, defaultdict(list)
    with (folder / 'roic_bands.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ok = r['status'] == 'ok'
            info[(r['security_code'], r['report_date'], r['available_at'])] = (ok, r['roic_path'])
            if not ok:
                rejected[r['security_code']].append((r['available_at'], r['report_date']))
    steps = {}
    for code, rows in rejected.items():
        rows.sort()
        keys, best, cur = [], [], ''
        for avail, report in rows:
            cur = max(cur, report)
            keys.append(avail); best.append(cur)
        steps[code] = (keys, best)
    return info, steps


def month_ends(path: Path, codes: set) -> dict:
    """(代码, 年月) → 当月最后一个状态行的 (日期, P/V, 带报告期, 带可得日)。"""
    out = {}
    with path.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, irp, iav, ipv = (h.index(k) for k in ('security_code', 'date', 'band_report_date', 'band_available_at', 'valuation_ratio'))
        for row in reader:
            code = row[ic]
            if code not in codes or row[idt] < START:
                continue
            key = (code, row[idt][:7])
            if key not in out or row[idt] > out[key][0]:
                out[key] = (row[idt], row[ipv], row[irp], row[iav])
    return out


def judge(rec, code, info, steps):
    """该臂的估值：float P/V，或无法估值的原因（none／stale）。"""
    if rec is None or not rec[1]:
        return 'none'
    day, pv, report, avail = rec
    band = info.get((code, report, avail))
    if band is None or not band[0]:
        return 'none'
    step = steps.get(code)
    if step:
        i = bisect.bisect_right(step[0], day)
        if i and step[1][i - 1] > report:
            return 'stale'
    value = float(pv)
    return value if value > 0 else 'none'


def load_spans() -> dict:
    spans = defaultdict(list)
    with PANEL.open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            spans[r['security_code'].zfill(6)].append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
    return spans


def load_tiers() -> dict:
    """代码 → [(生效起, 生效止, 档, 账面杠杆)]；年报不足 5 年的行杠杆为空。"""
    out = defaultdict(list)
    with TIERS_FILE.open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            out[r['security_code'].zfill(6)].append((r['effective_from'], r['effective_to'], r['tier'] if r['basis'] == 'baseline' else 'T4短',
                                                     float(r['leverage']) if r['leverage'] else None))
    return out


def tier_at(spans, day):
    for lo, hi, tier, lev in spans:
        if lo <= day <= hi:
            return tier, lev
    return '无档', None


def collect():
    bands = {a: load_bands(p) for a, p in BANDS.items()}
    # 样本代码 = 有 ROIC 路径 ok 带的公司（同 exp_oi217f「全部 ROIC」宇宙）∪ 面板公司（含其权益路径月份）；银行保险下面剔除
    codes = {k[0] for k, (ok, path) in bands['C'][0].items() if ok and path in ('growth', 'zero_growth')} | set(load_spans())
    names, industry = {}, {}
    with (ROOT / 'data/raw/a_share_securities.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            names[r['security_code'].zfill(6)] = r['security_name']
            industry[r['security_code'].zfill(6)] = gate(r.get('industry'))
    with (ROOT / 'data/processed/a_share_company_analysis_index.csv').open(newline='', encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            code = r['security_code'].zfill(6)
            names.setdefault(code, r['security_name'])
            if gate(r.get('industry')) != 'NA':
                industry[code] = gate(r.get('industry'))
    with PANEL.open(newline='', encoding='utf-8-sig') as f:   # 退市股只在面板表里有名称
        for r in csv.DictReader(f):
            names.setdefault(r['security_code'].zfill(6), r['security_name'])
    codes = {c for c in codes if not is_divspread_financial(c, names.get(c, ''))}
    states = {a: month_ends(p, codes) for a, p in STATES.items()}
    spans = load_spans()
    tiers = load_tiers()
    bhv.ACTIONS = FROZEN_ACTIONS
    actions = bhv.load_actions()
    by_code = defaultdict(list)
    for key in states['C']:
        by_code[key[0]].append(key)
    rows = []
    for code in sorted(codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, actions.get(code, []))
        for key in sorted(by_code.get(code, ())):
            pv = {a: judge(states[a].get(key), code, *bands[a]) for a in ARMS}
            if not isinstance(pv['C'], float):
                continue
            rec = states['C'][key]
            path = bands['C'][0].get((code, rec[2], rec[3]), (None, ''))[1]
            day = rec[0]
            fwd = {h: (forward_annualized(tr, days, day, h) if day in tr else None) for h in HORIZONS}
            tier, lev = tier_at(tiers.get(code, ()), day)
            rows.append(dict(code=code, name=names.get(code, ''), industry=industry.get(code, 'NA'), month=key[1], date=day,
                             path=path, panel=any(a <= day <= b for a, b in spans.get(code, ())),
                             pv_C=pv['C'], pv_G=pv['G'], f3=fwd[3], f5=fwd[5], tier=tier, leverage=lev))
    return rows


# ---------- 统计工具（同 exp_oi217f） ----------

def demean(groups, w, *cols):
    total = np.bincount(groups, weights=w)
    safe = np.where(total > 0, total, 1.0)
    return [c - (np.bincount(groups, weights=w * c) / safe)[groups] for c in cols]


def wls(y, X, w):
    Xw = X * w[:, None]
    return np.linalg.solve(X.T @ Xw, Xw.T @ y)


def boot_weights(stock_idx, n_stocks, rng):
    counts = np.bincount(rng.integers(0, n_stocks, n_stocks), minlength=n_stocks).astype(float)
    return counts[stock_idx]


def interval(values):
    v = np.asarray([x for x in values if np.isfinite(x)])
    return [float(np.percentile(v, 5)), float(np.percentile(v, 95))] if len(v) else [None, None]


def newey_west_t(series, lag):
    x = np.asarray(series, float)
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else None


def verdict(ci):
    """预登记判定：λ 的 90% 区间与 0、1 的关系。"""
    lo, hi = ci
    if lo is None:
        return '不可判'
    has0, has1 = lo <= 0 <= hi, lo <= 1 <= hi
    if has1 and not has0:
        return '数据支持该调整'
    if has0 and not has1:
        return '不支持，现口径更准'
    if not has0 and not has1:
        return '按点估计报比例'
    return '不能区分'


class Sample:
    """一个总体、一个期限的共同样本数组。"""

    def __init__(self, rows, horizon, clip=True, winsor=False):
        rows = [r for r in rows if isinstance(r['pv_G'], float) and r[f'f{horizon}'] is not None]
        if clip:
            rows = [r for r in rows if PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1]]
        self.rows = rows
        self.y = np.log1p(np.array([r[f'f{horizon}'] for r in rows]))
        self.x = np.log(np.array([r['pv_C'] for r in rows]))
        self.xg = np.log(np.array([r['pv_G'] for r in rows]))
        self.d = self.xg - self.x
        if winsor:
            for name in ('x', 'd'):
                v = getattr(self, name)
                lo, hi = np.percentile(v, [1, 99])
                setattr(self, name, np.clip(v, lo, hi))
        self.dn, self.dp = np.minimum(self.d, 0.0), np.maximum(self.d, 0.0)   # V 升一侧（降 r）、V 降一侧（升 r）
        codes = {c: i for i, c in enumerate(sorted({r['code'] for r in rows}))}
        self.stock = np.array([codes[r['code']] for r in rows], int)
        self.n_stocks = len(codes)
        months = {m: i for i, m in enumerate(sorted({r['month'] for r in rows}))}
        self.month = np.array([months[r['month']] for r in rows], int)
        cells = sorted({(r['month'], r['industry']) for r in rows})
        index = {c: i for i, c in enumerate(cells)}
        self.cell = np.array([index[(r['month'], r['industry'])] for r in rows], int)


def encompass(s: Sample, w, groups, regressors):
    cols = demean(groups, w, s.y, *(getattr(s, k) for k in regressors))
    X = np.column_stack(cols[1:])
    try:
        return wls(cols[0], X, w)
    except np.linalg.LinAlgError:   # 增速腿近乎单侧：V 降一侧股票很少，某次重抽整侧缺席、该列全零
        return np.full(X.shape[1], np.nan)


def readout_encompass(s: Sample, rng, fe='month'):
    groups = s.month if fe == 'month' else s.cell
    one = np.ones(len(s.y))
    out = {}
    for label, regs in (('合并', ('x', 'd')), ('分侧', ('x', 'dn', 'dp'))):
        beta = encompass(s, one, groups, regs)
        draws = [encompass(s, boot_weights(s.stock, s.n_stocks, rng), groups, regs) for _ in range(BOOT)]
        entry = dict(b=float(beta[0]), b_ci=interval([d[0] for d in draws]),
                     singular_draws=int(sum(not np.all(np.isfinite(d)) for d in draws)))
        for i, name in enumerate(regs[1:], 1):
            ci = interval([d[i] / d[0] for d in draws])
            nz = getattr(s, name) != 0
            entry[f'n_{name}'] = int(nz.sum())
            entry[f'stocks_{name}'] = int(len(set(s.stock[nz])))
            entry[f'g_{name}'] = float(beta[i])
            entry[f'lambda_{name}'] = float(beta[i] / beta[0])
            entry[f'lambda_{name}_ci'] = ci
            entry[f'verdict_{name}'] = verdict(ci)
        out[label] = entry
    return out


def calibrate(s: Sample, w):
    """一致组月效应 + 共同斜率；返回 (b, 各月截距, 可用月份掩码)。"""
    neutral = np.abs(s.d) < NEUTRAL
    wn = w * neutral
    ym, xm = demean(s.month, wn, s.y, s.x)
    b = float((wn * xm) @ ym / ((wn * xm) @ xm))
    total = np.bincount(s.month, weights=wn, minlength=s.month.max() + 1)
    safe = np.where(total > 0, total, 1.0)
    a = (np.bincount(s.month, weights=wn * s.y, minlength=len(total)) - b * np.bincount(s.month, weights=wn * s.x, minlength=len(total))) / safe
    return b, a, total > 0


def residuals(s: Sample, w, b, a, has, mask):
    m = mask & has[s.month]
    weight = w * m
    if weight.sum() == 0:
        return {k: None for k in ARMS}
    return {arm: float((weight * (s.y - (a[s.month] + b * xs))).sum() / weight.sum()) for arm, xs in (('C', s.x), ('G', s.xg))}


def groups_of(s: Sample):
    return {'V升分歧': s.d <= -DISPUTED, 'V降分歧': s.d >= DISPUTED, '全部分歧': np.abs(s.d) >= DISPUTED}


def readout_calibration(s: Sample, rng):
    groups = groups_of(s)
    one = np.ones(len(s.y))
    b, a, has = calibrate(s, one)
    out = dict(b=b, n_neutral=int((np.abs(s.d) < NEUTRAL).sum()))
    draws = []
    for _ in range(BOOT):
        w = boot_weights(s.stock, s.n_stocks, rng)
        bb, aa, hh = calibrate(s, w)
        draws.append({g: residuals(s, w, bb, aa, hh, m) for g, m in groups.items()})
    for g, m in groups.items():
        point = residuals(s, one, b, a, has, m)
        n = int((m & has[s.month]).sum())
        entry = dict(n=n, stocks=int(len(set(s.stock[m & has[s.month]]))), mean_d=float(s.d[m].mean()) if n else None)
        for arm in ARMS:
            entry[arm] = point[arm]
            entry[f'{arm}_ci'] = interval([d[g][arm] for d in draws if d[g][arm] is not None])
        entry['G_minus_C_abs'] = (abs(point['G']) - abs(point['C'])) if n else None
        out[g] = entry
    table = {}
    neutral = np.abs(s.d) < NEUTRAL
    for arm, xs in (('C', s.x), ('G', s.xg)):
        cells = []
        for lo, hi in BUCKETS:
            inb = (xs >= math.log(lo)) & (xs < math.log(hi))
            nb = np.exp(s.y[neutral & (s.x >= math.log(lo)) & (s.x < math.log(hi))]) - 1
            row = dict(bucket=f'[{lo:g},{hi:g})', neutral_median=float(np.median(nb)) if len(nb) >= 20 else None, neutral_n=int(len(nb)))
            for g, m in groups.items():
                db = np.exp(s.y[m & inb]) - 1
                row[f'{g}_median'] = float(np.median(db)) if len(db) >= 20 else None
                row[f'{g}_n'] = int(len(db))
            cells.append(row)
        table[arm] = cells
    out['buckets'] = table
    return out


def readout_tier_groups(s: Sample, rng):
    """按档与账面杠杆组（净现金／净负债低半／净负债高半，OI-221）的一致组校准残差：C 与 G 谁更接近 0。"""
    tier = np.array([r['tier'] for r in s.rows])
    lev = np.array([np.nan if r['leverage'] is None else r['leverage'] for r in s.rows])
    pos = lev[np.isfinite(lev) & (lev > 0)]
    cut = float(np.median(pos)) if len(pos) else 0.0
    masks = {f'档{t}': tier == t for t in ('T1', 'T2', 'T3', 'T4', 'T5', 'T4短', '无档')}
    masks |= {'净现金': np.isfinite(lev) & (lev <= 0), '净负债低半': np.isfinite(lev) & (lev > 0) & (lev <= cut),
              '净负债高半': np.isfinite(lev) & (lev > cut)}
    one = np.ones(len(s.y))
    b, a, has = calibrate(s, one)
    draws = []
    for _ in range(BOOT):
        w = boot_weights(s.stock, s.n_stocks, rng)
        bb, aa, hh = calibrate(s, w)
        draws.append({g: residuals(s, w, bb, aa, hh, m) for g, m in masks.items()})
    out = dict(leverage_cut=cut)
    for g, m in masks.items():
        n = int((m & has[s.month]).sum())
        if not n:
            out[g] = dict(n=0)
            continue
        point = residuals(s, one, b, a, has, m)
        entry = dict(n=n, stocks=int(len(set(s.stock[m & has[s.month]]))), mean_d=float(s.d[m].mean()))
        for arm in ARMS:
            entry[arm] = point[arm]
            entry[f'{arm}_ci'] = interval([d[g][arm] for d in draws if d[g][arm] is not None])
        entry['G_minus_C_abs'] = abs(point['G']) - abs(point['C'])
        out[g] = entry
    return out


def readout_by_stock(s: Sample):
    """逐股：分歧组平均残差、G 更接近 0 的只数、逐只剔除后的池化均值范围。"""
    b, a, has = calibrate(s, np.ones(len(s.y)))
    out = {}
    for label, m in groups_of(s).items():
        if label == '全部分歧':
            continue
        m = m & has[s.month]
        rc = s.y - (a[s.month] + b * s.x)
        rg = s.y - (a[s.month] + b * s.xg)
        by = defaultdict(list)
        for i in np.where(m)[0]:
            by[(s.rows[i]['code'], s.rows[i]['name'])].append(i)
        stocks = [dict(code=c, name=n, n=len(ix), C=float(rc[ix].mean()), G=float(rg[ix].mean())) for (c, n), ix in by.items()]
        idx = np.where(m)[0]
        loo_c, loo_g = [], []
        for (c, n), ix in by.items():
            rest = np.setdiff1d(idx, ix)
            if len(rest):
                loo_c.append(float(rc[rest].mean())); loo_g.append(float(rg[rest].mean()))
        out[label] = dict(stocks=len(stocks), G_closer=sum(abs(x['G']) < abs(x['C']) for x in stocks),
                          loo_C=[min(loo_c), max(loo_c)] if loo_c else None, loo_G=[min(loo_g), max(loo_g)] if loo_g else None,
                          by_stock=sorted(stocks, key=lambda x: -x['n']))
    return out


def readout_rank(s: Sample, lag):
    per = defaultdict(list)
    for t in np.unique(s.month):
        m = s.month == t
        if m.sum() < 10:
            continue
        ry = rankdata(s.y[m])
        for arm, xs in (('C', s.x), ('G', s.xg)):
            per[arm].append(float(np.corrcoef(rankdata(xs[m]), ry)[0, 1]))
    out = {arm: dict(mean=float(np.mean(v)), months=len(v)) for arm, v in per.items()}
    diff = np.array(per['G']) - np.array(per['C'])
    out['G-C'] = dict(mean=float(diff.mean()), nw_t=newey_west_t(diff, lag), better_share=float((diff < 0).mean()))
    return out


def readout_rejections(rows, horizon, s_all: Sample, rng):
    """一臂可估、另一臂无法估值的观测：按一致组校准在可估一臂 P/V 处的平均残差。"""
    b, a, has = calibrate(s_all, np.ones(len(s_all.y)))
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in s_all.rows}))}
    rej = [r for r in rows if not isinstance(r['pv_G'], float) and r[f'f{horizon}'] is not None
           and PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1] and r['month'] in months and has[months[r['month']]]]
    if not rej:
        return dict(n=0)
    y = np.log1p(np.array([r[f'f{horizon}'] for r in rej]))
    t = np.array([months[r['month']] for r in rej])
    resid = y - (a[t] + b * np.log(np.array([r['pv_C'] for r in rej])))
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in rej}))}
    idx = np.array([codes[r['code']] for r in rej], int)
    draws = []
    for _ in range(BOOT):
        w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[idx]
        if w.sum():
            draws.append(float((w * resid).sum() / w.sum()))
    return dict(n=len(rej), stocks=len(codes), mean_resid=float(resid.mean()), ci=interval(draws),
                reasons=dict(Counter(r['pv_G'] for r in rej)), top=Counter(r['name'] for r in rej).most_common(8))


def readout_disagreement(s: Sample):
    q = [5, 25, 50, 75, 95]
    by = defaultdict(list)
    for r, d in zip(s.rows, s.d):
        by[(r['code'], r['name'])].append(d)
    stocks = [dict(code=c, name=n, months=len(v), mean_d=float(np.mean(v))) for (c, n), v in by.items()]
    return dict(n=len(s.y), stocks=s.n_stocks, d=dict(zip(map(str, q), map(float, np.percentile(s.d, q)))),
                share_abs_ge_010=float((np.abs(s.d) >= 0.10).mean()), share_neutral=float((np.abs(s.d) < NEUTRAL).mean()),
                share_peak_side=float((s.d <= -DISPUTED).mean()), share_trough_side=float((s.d >= DISPUTED).mean()),
                by_path=dict(Counter(r['path'] for r, d in zip(s.rows, s.d) if abs(d) >= DISPUTED)),
                top_peak=sorted(stocks, key=lambda x: x['mean_d'])[:10], top_trough=sorted(stocks, key=lambda x: -x['mean_d'])[:10])


def cases(rows):
    """读数 F6：面板共同样本 3 年前向 ≥ 24 个月者，平均 d 最负 4 只（V 升）与最正 4 只（V 降），加预登记具名。"""
    s3 = Sample([r for r in rows if r['panel']], 3)
    b, a, has = calibrate(s3, np.ones(len(s3.y)))
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in s3.rows}))}
    by = defaultdict(list)
    for r, d in zip(s3.rows, s3.d):
        by[r['code']].append(d)
    eligible = {c: v for c, v in by.items() if len(v) >= 24}
    pick = sorted(eligible, key=lambda c: np.mean(eligible[c]))[:4]
    pick += [c for c in sorted(eligible, key=lambda c: -np.mean(eligible[c])) if c not in pick][:4]
    pick += [c for c in NAMED if c not in pick]
    table, errors = [], {}
    for code in pick:
        mine = [r for r in rows if r['code'] == code and r['panel']]
        for r in mine:
            if r['month'][5:] != '12':
                continue
            t = months.get(r['month'])
            pred = {arm: (math.expm1(a[t] + b * math.log(r[f'pv_{arm}'])) if isinstance(r[f'pv_{arm}'], float) and t is not None and has[t]
                          else None) for arm in ARMS}
            table.append(dict(code=code, name=r['name'], month=r['month'], path=r['path'], pv_C=r['pv_C'], pv_G=r['pv_G'],
                              f3=r['f3'], f5=r['f5'], pred3_C=pred['C'], pred3_G=pred['G']))
        common = [r for r in mine if r['f3'] is not None and r['month'] in months and has[months[r['month']]]
                  and PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1] and isinstance(r['pv_G'], float)]
        err = dict(months=len(common), g_unvaluable=sum(not isinstance(r['pv_G'], float) for r in mine))
        for arm in ARMS:
            resid = [math.log1p(r['f3']) - (a[months[r['month']]] + b * math.log(r[f'pv_{arm}'])) for r in common]
            err[arm] = dict(mae=float(np.mean(np.abs(resid))) if resid else None, bias=float(np.mean(resid)) if resid else None)
        errors[code] = err
    return pick, table, errors


def main():
    rows = collect()
    cache = EXP / 'cache'
    cache.mkdir(exist_ok=True)
    with (cache / ('test_fairness_observations.csv' if TEST else f'fairness_observations_{FAIR_ARM}.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    rng = np.random.default_rng(20260928)
    results = dict(test=TEST, boot=BOOT, observations=len(rows),
                   status_counts=dict(Counter(r['pv_G'] if not isinstance(r['pv_G'], float) else 'ok' for r in rows)))
    for universe, sel in (('面板', [r for r in rows if r['panel']]), ('全部', rows),
                          ('面板2015起', [r for r in rows if r['panel'] and r['month'] >= '2015-01']),
                          ('全部2015起', [r for r in rows if r['month'] >= '2015-01'])):
        for h in HORIZONS:
            key = f'{universe}_{h}y'
            s = Sample(sel, h)
            entry = dict(disagreement=readout_disagreement(s), rank=readout_rank(s, 12 * h),
                         encompass=readout_encompass(s, rng), encompass_industry=readout_encompass(s, rng, fe='cell'),
                         encompass_unclipped=readout_encompass(Sample(sel, h, clip=False, winsor=True), rng),
                         calibration=readout_calibration(s, rng), rejections=readout_rejections(sel, h, s, rng),
                         calibration_by_stock=readout_by_stock(s), tier_groups=readout_tier_groups(s, rng))
            results[key] = entry
            e = entry['encompass']['分侧']
            print(key, 'n', len(s.y), 'stocks', s.n_stocks, 'b %.3f' % e['b'],
                  'λV升 %.2f %s %s' % (e['lambda_dn'], e['lambda_dn_ci'], e['verdict_dn']),
                  'λV降 %.2f %s %s (n %d, stocks %d, singular %d)' % (e['lambda_dp'], e['lambda_dp_ci'], e['verdict_dp'],
                                                                    e['n_dp'], e['stocks_dp'], e['singular_draws']), flush=True)
    pick, table, errors = cases(rows)
    results['cases'] = dict(picked=pick, errors=errors)
    (OUT / ('test_fairness.json' if TEST else f'fairness_{FAIR_ARM}.json')).write_text(json.dumps(results, ensure_ascii=False, indent=1) + '\n')
    with (OUT / ('test_fairness_cases.csv' if TEST else f'fairness_cases_{FAIR_ARM}.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader(); w.writerows(table)


if __name__ == '__main__':
    main()
