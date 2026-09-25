"""OI-217 估值公允性检验（preregister.md）：三种 WACC 权重的 `P/V` 对其后 3／5 年含分红总回报。

    python3 fairness.py          # 读数 1～6 → results.json、cases.csv；逐月观测写 cache/observations.csv
    EXP_TEST=1 python3 fairness.py   # 冒烟：面板子集状态、W 以 C 代替、重抽 50 次，只写 cache/
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
SRC = ROOT / 'data/experiments/exp_oi217u_20260925'
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import build_historical_valuation_bands as bhv  # noqa: E402
from divspread_names import is_divspread_financial  # noqa: E402
from moat_param_lab import forward_annualized, total_return_index  # noqa: E402

TEST = os.environ.get('EXP_TEST') == '1'
BANDS = {'C': SRC / 'states/CONTROL_build', 'W': EXP / 'states/W_build', 'U': SRC / 'states/WU_build'}
STATES = {a: p / 'a_share_daily_states_adopted.csv' for a, p in BANDS.items()}
if TEST:
    BANDS['W'] = BANDS['C']
    STATES = {'C': SRC / 'states/CONTROL/a_share_daily_states_adopted.csv', 'U': SRC / 'states/WU/a_share_daily_states_adopted.csv'}
    STATES['W'] = STATES['C']
OUT = EXP / 'cache' if TEST else EXP
PANEL = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
START = '2007-01-01'
ROIC_PATHS = {'growth', 'zero_growth'}
PV_RANGE = (0.2, 5.0)
NEUTRAL, DISPUTED, SHARE = 0.02, 0.15, 0.75
BOOT = 50 if TEST else 1000
HORIZONS = (3, 5)
NAMED = ('000651', '600900')
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
    """行键 → (ok, ROIC 路径)；逐票拒绝带的「可得日 → 已拒最新报告期」阶梯，用于判沿用旧带。"""
    info, rejected = {}, defaultdict(list)
    with (folder / 'roic_bands.csv').open(newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ok = r['status'] == 'ok'
            info[(r['security_code'], r['report_date'], r['available_at'])] = (ok, r['roic_path'] in ROIC_PATHS)
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
    """该臂的估值：float P/V，或无法估值的原因。"""
    if rec is None or not rec[1]:
        return 'none'
    day, pv, report, avail = rec
    band = info.get((code, report, avail))
    if band is None or not band[0]:
        return 'none'
    if not band[1]:
        return 'equity'
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


def collect():
    bands = {a: load_bands(p) for a, p in BANDS.items()}
    info_c = bands['C'][0]
    codes = {k[0] for k, (ok, roic) in info_c.items() if ok and roic}
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
            pv = {a: judge(states[a].get(key), code, *bands[a]) for a in ('C', 'W', 'U')}
            if not isinstance(pv['C'], float):
                continue
            if TEST and isinstance(pv['U'], float):   # 冒烟用的合成 W：按代码取 C 与 U 之间的固定比例，避免与 d_U 共线
                pv['W'] = pv['C'] * (pv['U'] / pv['C']) ** ((int(code) % 7) / 7)
            day = states['C'][key][0]
            fwd = {h: (forward_annualized(tr, days, day, h) if day in tr else None) for h in HORIZONS}
            rows.append(dict(code=code, name=names.get(code, ''), industry=industry.get(code, 'NA'), month=key[1], date=day,
                             panel=any(a <= day <= b for a, b in spans.get(code, ())), pv_C=pv['C'], pv_W=pv['W'], pv_U=pv['U'],
                             f3=fwd[3], f5=fwd[5]))
    return rows


# ---------- 统计工具 ----------

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


class Sample:
    """一个总体、一个期限的共同样本数组。"""

    def __init__(self, rows, horizon, clip=True, winsor=False):
        rows = [r for r in rows if isinstance(r['pv_W'], float) and isinstance(r['pv_U'], float) and r[f'f{horizon}'] is not None]
        if clip:
            rows = [r for r in rows if PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1]]
        self.rows = rows
        self.y = np.log1p(np.array([r[f'f{horizon}'] for r in rows]))
        self.x = np.log(np.array([r['pv_C'] for r in rows]))
        self.xw = np.log(np.array([r['pv_W'] for r in rows]))
        self.xu = np.log(np.array([r['pv_U'] for r in rows]))
        self.dW, self.dU = self.xw - self.x, self.xu - self.xw
        if winsor:
            for name in ('x', 'dW', 'dU'):
                v = getattr(self, name)
                lo, hi = np.percentile(v, [1, 99])
                setattr(self, name, np.clip(v, lo, hi))
        self.dT = self.dW + self.dU
        codes = {c: i for i, c in enumerate(sorted({r['code'] for r in rows}))}
        self.stock = np.array([codes[r['code']] for r in rows], int)
        self.n_stocks = len(codes)
        months = {m: i for i, m in enumerate(sorted({r['month'] for r in rows}))}
        self.month = np.array([months[r['month']] for r in rows], int)
        cells = sorted({(r['month'], r['industry']) for r in rows})
        index = {c: i for i, c in enumerate(cells)}
        self.cell = np.array([index[(r['month'], r['industry'])] for r in rows], int)


def encompass(s: Sample, w, groups, regressors=('x', 'dW', 'dU')):
    cols = demean(groups, w, s.y, *(getattr(s, k) for k in regressors))
    beta = wls(cols[0], np.column_stack(cols[1:]), w)
    return beta


def readout_encompass(s: Sample, rng, fe='month'):
    groups = s.month if fe == 'month' else s.cell
    one = np.ones(len(s.y))
    out = {}
    for label, regs in (('三臂', ('x', 'dW', 'dU')), ('C对U', ('x', 'dT'))):
        beta = encompass(s, one, groups, regs)
        draws = [encompass(s, boot_weights(s.stock, s.n_stocks, rng), groups, regs) for _ in range(BOOT)]
        entry = dict(b=float(beta[0]), b_ci=interval([d[0] for d in draws]))
        for i, name in enumerate(regs[1:], 1):
            entry[f'g_{name}'] = float(beta[i])
            entry[f'lambda_{name}'] = float(beta[i] / beta[0])
            entry[f'lambda_{name}_ci'] = interval([d[i] / d[0] for d in draws])
        out[label] = entry
    return out


def calibrate(s: Sample, w):
    """一致组月效应 + 共同斜率；返回 (b, 各月截距, 可用月份掩码)。"""
    neutral = np.abs(s.dT) < NEUTRAL
    wn = w * neutral
    ym, xm = demean(s.month, wn, s.y, s.x)
    b = float((wn * xm) @ ym / ((wn * xm) @ xm))
    total = np.bincount(s.month, weights=wn, minlength=s.month.max() + 1)
    safe = np.where(total > 0, total, 1.0)
    a = (np.bincount(s.month, weights=wn * s.y, minlength=len(total)) - b * np.bincount(s.month, weights=wn * s.x, minlength=len(total))) / safe
    return b, a, total > 0


def residuals(s: Sample, w, b, a, has, mask):
    """分歧组（mask）按三臂 P/V 代入一致组校准的平均残差（对数年化）。"""
    m = mask & has[s.month]
    weight = w * m
    if weight.sum() == 0:
        return {k: None for k in 'CWU'}
    out = {}
    for arm, xs in (('C', s.x), ('W', s.xw), ('U', s.xu)):
        out[arm] = float((weight * (s.y - (a[s.month] + b * xs))).sum() / weight.sum())
    return out


def readout_calibration(s: Sample, rng):
    groups = {'全部分歧': s.dT >= DISPUTED}
    groups['净现金型'] = groups['全部分歧'] & (s.dW >= SHARE * s.dT)
    groups['净负债型'] = groups['全部分歧'] & (s.dU >= SHARE * s.dT)
    groups['混合型'] = groups['全部分歧'] & ~groups['净现金型'] & ~groups['净负债型']
    one = np.ones(len(s.y))
    b, a, has = calibrate(s, one)
    out = dict(b=b, n_neutral=int((np.abs(s.dT) < NEUTRAL).sum()))
    draws = []
    for _ in range(BOOT):
        w = boot_weights(s.stock, s.n_stocks, rng)
        bb, aa, hh = calibrate(s, w)
        draws.append({g: residuals(s, w, bb, aa, hh, m) for g, m in groups.items()})
    for g, m in groups.items():
        point = residuals(s, one, b, a, has, m)
        n = int((m & has[s.month]).sum())
        entry = dict(n=n, stocks=int(len(set(s.stock[m & has[s.month]]))), mean_dT=float(s.dT[m].mean()) if n else None)
        for arm in 'CWU':
            entry[arm] = point[arm]
            entry[f'{arm}_ci'] = interval([d[g][arm] for d in draws if d[g][arm] is not None])
        out[g] = entry
    # 分桶：分歧组按各臂 P/V 分桶的回报中位 vs 一致组同桶（年化）
    table = {}
    neutral = np.abs(s.dT) < NEUTRAL
    for arm, xs in (('C', s.x), ('W', s.xw), ('U', s.xu)):
        cells = []
        for lo, hi in BUCKETS:
            inb = (xs >= math.log(lo)) & (xs < math.log(hi))
            nb = np.exp(s.y[neutral & (s.x >= math.log(lo)) & (s.x < math.log(hi))]) - 1
            db = np.exp(s.y[groups['全部分歧'] & inb]) - 1
            cells.append(dict(bucket=f'[{lo:g},{hi:g})', neutral_median=float(np.median(nb)) if len(nb) >= 20 else None, neutral_n=int(len(nb)),
                              disputed_median=float(np.median(db)) if len(db) >= 20 else None, disputed_n=int(len(db))))
        table[arm] = cells
    out['buckets'] = table
    return out


def readout_by_stock(s: Sample):
    """补充（预登记外）：分歧组逐股平均残差、C／U 残差为负与 U 更接近 0 的只数、逐只剔除后的池化均值范围。"""
    b, a, has = calibrate(s, np.ones(len(s.y)))
    dis = s.dT >= DISPUTED
    out = {}
    for label, m in (('净负债型', dis & (s.dU >= SHARE * s.dT)), ('净现金型', dis & (s.dW >= SHARE * s.dT))):
        m = m & has[s.month]
        rc = s.y - (a[s.month] + b * s.x)
        ru = s.y - (a[s.month] + b * s.xu)
        by = defaultdict(list)
        for i in np.where(m)[0]:
            by[(s.rows[i]['code'], s.rows[i]['name'])].append(i)
        stocks = [dict(code=c, name=n, n=len(ix), C=float(rc[ix].mean()), U=float(ru[ix].mean())) for (c, n), ix in by.items()]
        idx = np.where(m)[0]
        loo_c, loo_u = [], []
        for (c, n), ix in by.items():
            rest = np.setdiff1d(idx, ix)
            if len(rest):
                loo_c.append(float(rc[rest].mean())); loo_u.append(float(ru[rest].mean()))
        out[label] = dict(stocks=len(stocks), C_negative=sum(x['C'] < 0 for x in stocks), U_negative=sum(x['U'] < 0 for x in stocks),
                          U_closer=sum(abs(x['U']) < abs(x['C']) for x in stocks),
                          loo_C=[min(loo_c), max(loo_c)] if loo_c else None, loo_U=[min(loo_u), max(loo_u)] if loo_u else None,
                          by_stock=sorted(stocks, key=lambda x: -x['n']))
    return out


def readout_rank(s: Sample, lag):
    per = defaultdict(list)
    for t in np.unique(s.month):
        m = s.month == t
        if m.sum() < 10:
            continue
        ry = rankdata(s.y[m])
        for arm, xs in (('C', s.x), ('W', s.xw), ('U', s.xu)):
            per[arm].append(float(np.corrcoef(rankdata(xs[m]), ry)[0, 1]))
    out = {arm: dict(mean=float(np.mean(v)), months=len(v)) for arm, v in per.items()}
    for a, b in (('W', 'C'), ('U', 'C'), ('U', 'W')):
        diff = np.array(per[a]) - np.array(per[b])
        out[f'{a}-{b}'] = dict(mean=float(diff.mean()), nw_t=newey_west_t(diff, lag), better_share=float((diff < 0).mean()))
    return out


def readout_rejections(rows, horizon, s_all: Sample, rng):
    """C 可估、U（或 W）无法估值的观测：按一致组校准在 PV_C 处的平均残差。"""
    one = np.ones(len(s_all.y))
    b, a, has = calibrate(s_all, one)
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in s_all.rows}))}
    out = {}
    for arm in ('U', 'W'):
        rej = [r for r in rows if not isinstance(r[f'pv_{arm}'], float) and r[f'f{horizon}'] is not None
               and PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1] and r['month'] in months and has[months[r['month']]]]
        if not rej:
            out[arm] = dict(n=0)
            continue
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
        reasons = Counter(r[f'pv_{arm}'] for r in rej)
        top = Counter(r['name'] for r in rej).most_common(8)
        out[arm] = dict(n=len(rej), stocks=len(codes), mean_resid=float(resid.mean()), ci=interval(draws), reasons=dict(reasons), top=top)
    return out


def readout_disagreement(s: Sample):
    q = [5, 25, 50, 75, 95]
    by = defaultdict(list)
    for r, dw, du in zip(s.rows, s.dW, s.dU):
        by[(r['code'], r['name'])].append((dw, du))
    stocks = [dict(code=c, name=n, months=len(v), mean_dW=float(np.mean([x for x, _ in v])), mean_dU=float(np.mean([y for _, y in v])))
              for (c, n), v in by.items()]
    return dict(n=len(s.y), stocks=s.n_stocks,
                dW=dict(zip(map(str, q), map(float, np.percentile(s.dW, q)))),
                dU=dict(zip(map(str, q), map(float, np.percentile(s.dU, q)))),
                share_dT_ge_010=float((s.dT >= 0.10).mean()), share_neutral=float((np.abs(s.dT) < NEUTRAL).mean()),
                top_dW=sorted(stocks, key=lambda x: -x['mean_dW'])[:10], top_dU=sorted(stocks, key=lambda x: -x['mean_dU'])[:10])


def cases(rows):
    """读数 6：面板共同样本 3 年前向 ≥ 24 个月者，平均 d_W 前 4 与平均 d_U 前 4，加格力、长江电力。"""
    s3 = Sample([r for r in rows if r['panel']], 3)
    b, a, has = calibrate(s3, np.ones(len(s3.y)))
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in s3.rows}))}
    by = defaultdict(list)
    for r, dw, du in zip(s3.rows, s3.dW, s3.dU):
        by[r['code']].append((dw, du))
    eligible = {c: v for c, v in by.items() if len(v) >= 24}
    pick = sorted(eligible, key=lambda c: -np.mean([x for x, _ in eligible[c]]))[:4]
    pick += [c for c in sorted(eligible, key=lambda c: -np.mean([y for _, y in eligible[c]])) if c not in pick][:4]
    pick += [c for c in NAMED if c not in pick]
    table = []
    for code in pick:
        mine = [r for r in rows if r['code'] == code and r['panel'] and r['month'] >= START[:7]]
        for r in mine:
            if r['month'][5:] != '12':
                continue
            t = months.get(r['month'])
            pred = {}
            for arm in 'CWU':
                pv = r[f'pv_{arm}']
                pred[arm] = (math.expm1(a[t] + b * math.log(pv)) if isinstance(pv, float) and t is not None and has[t] else None)
            table.append(dict(code=code, name=r['name'], month=r['month'], pv_C=r['pv_C'],
                              pv_W=r['pv_W'] if isinstance(r['pv_W'], float) else r['pv_W'],
                              pv_U=r['pv_U'] if isinstance(r['pv_U'], float) else r['pv_U'],
                              f3=r['f3'], f5=r['f5'], pred3_C=pred['C'], pred3_W=pred['W'], pred3_U=pred['U']))
    errors = {}
    for code in pick:
        mine = [r for r in rows if r['code'] == code and r['panel'] and r['f3'] is not None and r['month'] in months
                and has[months[r['month']]] and PV_RANGE[0] <= r['pv_C'] <= PV_RANGE[1]]
        common = [r for r in mine if all(isinstance(r[f'pv_{arm}'], float) for arm in 'CWU')]   # 三臂同一批月份
        err = dict(months=len(mine), common=len(common), u_unvaluable=sum(not isinstance(r['pv_U'], float) for r in mine))
        for arm in 'CWU':
            resid = [math.log1p(r['f3']) - (a[months[r['month']]] + b * math.log(r[f'pv_{arm}'])) for r in common]
            err[arm] = dict(mae=float(np.mean(np.abs(resid))) if resid else None, bias=float(np.mean(resid)) if resid else None)
        errors[code] = err
    return pick, table, errors


def main():
    rows = collect()
    cache = EXP / 'cache'
    cache.mkdir(exist_ok=True)
    with (cache / ('test_observations.csv' if TEST else 'observations.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    rng = np.random.default_rng(20260925)
    results = dict(test=TEST, boot=BOOT, observations=len(rows),
                   status_counts={arm: dict(Counter(r[f'pv_{arm}'] if not isinstance(r[f'pv_{arm}'], float) else 'ok' for r in rows)) for arm in 'WU'})
    for universe, sel in (('面板', [r for r in rows if r['panel']]), ('全部ROIC', rows)):
        for h in HORIZONS:
            key = f'{universe}_{h}y'
            s = Sample(sel, h)
            entry = dict(disagreement=readout_disagreement(s), rank=readout_rank(s, 12 * h),
                         encompass=readout_encompass(s, rng), encompass_industry=readout_encompass(s, rng, fe='cell'),
                         encompass_unclipped=readout_encompass(Sample(sel, h, clip=False, winsor=True), rng),
                         calibration=readout_calibration(s, rng), rejections=readout_rejections(sel, h, s, rng),
                         calibration_by_stock=readout_by_stock(s))
            results[key] = entry
            e = entry['encompass']['三臂']
            print(key, 'n', len(s.y), 'stocks', s.n_stocks, 'b %.3f' % e['b'], 'λW %.2f %s' % (e['lambda_dW'], e['lambda_dW_ci']),
                  'λU %.2f %s' % (e['lambda_dU'], e['lambda_dU_ci']), flush=True)
    pick, table, errors = cases(rows)
    results['cases'] = dict(picked=pick, errors=errors)
    (OUT / ('test_results.json' if TEST else 'results.json')).write_text(json.dumps(results, ensure_ascii=False, indent=1) + '\n')
    with (OUT / ('test_cases.csv' if TEST else 'cases.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(table[0]))
        w.writeheader(); w.writerows(table)


if __name__ == '__main__':
    main()
