"""OI-223 探索性读数（未预登记）：同 `P/V` 下各组其后回报的差异。

样本 = OI-217 公允性检验的月末观测（`../exp_oi217f2_20260925/cache/observations.csv`，现行口径 `pv_U`，
`P/V` 夹 [0.2, 5]），分组 = 今日质量分档、今日策略标签、证监会行业门类（前两者含后视：今日的分档与标签
是看过结果后给的）。回归：其后 3／5 年年化对数总回报 ~ log(P/V) + 组哑变量，月固定效应，按股票整簇自助 500 次
取 5%～95% 区间；组系数 = 同 `P/V` 下该组相对基准组的年化超额。

    python3 tier_calibration.py > results.txt
"""
import csv
import math
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
OBS = ROOT / 'data/experiments/exp_oi217f2_20260925/cache/observations.csv'
TIERS = ROOT / 'data/processed/a_share_watchlist_quality_tiers.csv'
BOOT = 500
TAGS = {'A': 'A现金流复利', 'C': 'C成长', 'D': 'D产业链', 'F': 'F资源', 'K': 'K稳态分配', 'H': 'H周期'}
SECTORS = {'C': '制造C', 'B': '采矿B', 'D': '公用D', 'I': '信息I', 'G': '交运G', 'F': '批零F', 'Q': '医疗Q'}


def number(v) -> bool:
    try:
        return math.isfinite(float(v))
    except ValueError:
        return False


def run(obs, tiers, horizon, key, label, base, panel_only=False):
    rng = np.random.default_rng(20260925)
    rows = [r for r in obs if number(r['pv_U']) and number(r[f'f{horizon}']) and 0.2 <= float(r['pv_U']) <= 5.0
            and (not panel_only or r['panel'] == 'True')]
    y = np.log1p(np.array([float(r[f'f{horizon}']) for r in rows]))
    x = np.log(np.array([float(r['pv_U']) for r in rows]))
    g = [key(r) for r in rows]
    groups = sorted(set(g) - {base})
    X = np.column_stack([x] + [np.array([gi == k for gi in g], float) for k in groups])
    months = {m: i for i, m in enumerate(sorted({r['month'] for r in rows}))}
    mi = np.array([months[r['month']] for r in rows])
    codes = {c: i for i, c in enumerate(sorted({r['code'] for r in rows}))}
    si = np.array([codes[r['code']] for r in rows])

    def fit(w):
        tot = np.bincount(mi, weights=w)
        safe = np.where(tot > 0, tot, 1)
        dm = lambda c: c - (np.bincount(mi, weights=w * c) / safe)[mi]
        yd = dm(y)
        xd = np.column_stack([dm(X[:, j]) for j in range(X.shape[1])])
        xw = xd * w[:, None]
        return np.linalg.solve(xd.T @ xw, xw.T @ yd)

    beta = fit(np.ones(len(y)))
    draws = []
    for _ in range(BOOT):
        cnt = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)
        try:
            draws.append(fit(cnt[si]))
        except np.linalg.LinAlgError:
            pass
    draws = np.array(draws)
    n_obs = {k: sum(1 for gi in g if gi == k) for k in groups + [base]}
    n_stk = {k: len({r['code'] for r, gi in zip(rows, g) if gi == k}) for k in groups + [base]}
    lo, hi = np.percentile(draws[:, 0], [5, 95])
    print(f"\n== {label} f{horizon}{' 面板内' if panel_only else ''}：斜率 b={beta[0]:+.3f} [{lo:+.3f},{hi:+.3f}]；基准组 {base} 观测 {n_obs[base]} 股 {n_stk[base]}")
    for j, k in enumerate(groups, 1):
        lo, hi = np.percentile(draws[:, j], [5, 95])
        print(f"  {k:<10} 同 P/V 年化超额 {beta[j]*100:+6.2f}% [{lo*100:+.2f},{hi*100:+.2f}]  观测 {n_obs[k]:>5} 股 {n_stk[k]:>3}")


def main():
    obs = list(csv.DictReader(OBS.open()))
    tiers = {r['security_code']: r for r in csv.DictReader(TIERS.open(encoding='utf-8-sig'))}
    tier = lambda r: tiers[r['code']]['quality_tier'] if r['code'] in tiers else 'NA(今日不在名单)'
    tag = lambda r: TAGS.get(tiers[r['code']]['primary_strategy_tag'][:1], '其他') if r['code'] in tiers else 'NA(今日不在名单)'
    for h in (3, 5):
        run(obs, tiers, h, tier, '今日质量分档', 'L2')
    run(obs, tiers, 3, tier, '今日质量分档', 'L2', panel_only=True)
    run(obs, tiers, 3, tag, '今日策略标签', 'C成长')
    run(obs, tiers, 3, tag, '今日策略标签', 'C成长', panel_only=True)
    run(obs, tiers, 3, lambda r: SECTORS.get(r['industry'], '其他'), '证监会门类', '制造C')


if __name__ == '__main__':
    main()
