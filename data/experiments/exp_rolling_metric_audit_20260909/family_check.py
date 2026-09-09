"""§12.222 证据：股债族 19 臂在旧主读数 M（起点内两臂滚五中位之差）与 m3 主读数 P（同窗口配对差）下的判定对照、EBDS03 逐起点离散与干预期窗口占比。输入：本目录 curves/（BASE 逐日净值，不入库）与 exp_equity_bond_20260909 两轮 daily/full_A 诊断；沿用 OI-169/170 原记账。"""
import csv, json, sys, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'data/experiments/exp_rolling_metric_audit_20260909'))
sys.path.insert(0, str(ROOT / 'scripts'))
import audit  # reuse windows()
EXP = ROOT / 'data/experiments/exp_rolling_metric_audit_20260909'
EB = ROOT / 'data/experiments/exp_equity_bond_20260909'
starts = json.loads((EXP / 'manifest.json').read_text())['starts']

# ---- 1. per-start dispersion and leave-one-start-out ranges for EBDS03 ----
rows = list(csv.DictReader(open(EXP / 'per_start.csv')))
print('== 1. EBDS03: per-start dispersion and leave-one-start-out (LOO) ranges ==')
for g in ('full', 'A'):
    M = [float(r['current_delta_pp']) for r in rows if r['group'] == g]
    P = [float(r['matched_window_median_pp']) for r in rows if r['group'] == g]
    C = [float(r['cagr_delta_pp']) for r in rows if r['group'] == g]
    for name, v in (('M', M), ('P', P), ('CAGR', C)):
        loo = [st.median(v[:i] + v[i+1:]) for i in range(len(v))]
        print(f'{g:>4} {name:>4}: median {st.median(v):+6.2f}  sd {st.pstdev(v):5.2f}  LOO range [{min(loo):+6.2f}, {max(loo):+6.2f}]  sign>0 {sum(x>0 for x in v)}/14')
    # sign agreement vs |M|
    agree = [(abs(m), (m > 0) == (p > 0)) for m, p in zip(M, P)]
    dis = [round(a, 2) for a, ok in agree if not ok]
    print(f'{g:>4} M/P sign disagreements at |M| = {dis}; min |M| among agreements = {min(a for a, ok in agree if ok):.2f}')

# ---- 2. overlap amplification: windows touching the intervention months ----
pw = list(csv.DictReader(open(EXP / 'paired_windows.csv')))
print('\n== 2. EBDS03 full sample: share of 5y windows overlapping intervention periods (2015-05..07, 2018-02) ==')
def overlaps(r, a, b):
    return r['window_from'] <= b and r['window_to'] >= a
for g in ('full',):
    tot = [r for r in pw if r['group'] == g]
    hit15 = [r for r in tot if overlaps(r, '2015-05-01', '2015-07-31')]
    hit18 = [r for r in tot if overlaps(r, '2018-02-01', '2018-02-28')]
    hit = [r for r in tot if overlaps(r, '2015-05-01', '2015-07-31') or overlaps(r, '2018-02-01', '2018-02-28')]
    miss = [r for r in tot if r not in hit]
    print(f'{g}: windows {len(tot)}, touching 2015 top {len(hit15)}, touching 2018 top {len(hit18)}, either {len(hit)} ({len(hit)/len(tot):.0%}), neither {len(miss)}')
    d_hit = [float(r['delta_pp']) for r in hit]; d_miss = [float(r['delta_pp']) for r in miss]
    print(f'   delta median: touching {st.median(d_hit):+.2f}pp (win {sum(x>0 for x in d_hit)/len(d_hit):.0%}); not touching {st.median(d_miss):+.2f}pp (win {sum(x>0 for x in d_miss)/len(d_miss):.0%}); n={len(d_hit)}/{len(d_miss)}')
    # by window end year: median delta across all (start,window) records
    print('   by window-end year: n, median delta, win%')
    by = {}
    for r in tot:
        by.setdefault(r['window_to'][:4], []).append(float(r['delta_pp']))
    for y in sorted(by):
        v = by[y]; print(f'     {y}: n={len(v):3d}  med {st.median(v):+6.2f}  win {sum(x>0 for x in v)/len(v):4.0%}')

# ---- 3. M vs P across the whole equity-bond family (both rounds) ----
print('\n== 3. Family-wide M vs P (pp), all candidate arms with daily diagnostics, vs audit BASE curves ==')
base_curves = {(g, s): json.loads((EXP / 'curves' / f'{g}_{s}.json').read_text()) for g in ('full', 'A') for s in starts}
base_w = {k: audit.windows(c) for k, c in base_curves.items()}
def load_candidate(path, base_curve):
    rows = list(csv.DictReader(open(path)))
    curve = [[r['date'], float(r['equity'])] for r in rows]
    if [r[0] for r in base_curve[1:]] == [r[0] for r in curve]:
        curve.insert(0, list(base_curve[0]))
    if [r[0] for r in base_curve] != [r[0] for r in curve]:
        return None
    return curve
arms = []
for d in (EB / 'high_base/daily/full_A', EB / 'daily/full_A'):
    names = sorted({p.name.lstrip('_')[:-4].rstrip('ex5')[:-8] for p in d.glob('_*.csv')})
    for a in names:
        arms.append((a, d))
print(f'{"arm":<10}{"round":<10}{"M_full":>8}{"P_full":>8}{"M_A":>8}{"P_A":>8}{"CAGR_full":>10}{"CAGR_A":>8}  M-rule  P-rule')
def rule(mf, ma, cf, ca):
    vals = [mf, ma, cf, ca]
    if all(v >= -0.15 for v in vals): return 'adopt'
    pairs = [(mf, ma), (ma, mf), (cf, ca), (ca, cf)]
    bad = [v for v in vals if v < -0.15]
    if len(bad) == 1:
        for x, y in pairs:
            if -1 <= x < -0.15 and y >= 1: return 'ruling'
    return 'reject'
for a, d in arms:
    out = {}
    ok = True
    for g in ('full', 'A'):
        Ms, Ps, Cs = [], [], []
        for s in starts:
            p = d / f'_{a}{s.replace("-", "")}{"ex5" if g == "A" else ""}.csv'
            if not p.exists(): ok = False; break
            c = load_candidate(p, base_curves[(g, s)])
            if c is None: ok = False; break
            w = audit.windows(c); b = base_w[(g, s)]
            assert [(x['from'], x['to']) for x in w] == [(x['from'], x['to']) for x in b]
            Ms.append((st.median(x['cagr'] for x in w) - st.median(x['cagr'] for x in b)) * 100)
            Ps.append(st.median((x['cagr'] - y['cagr']) * 100 for x, y in zip(w, b)))
            yrs = (audit.datetime.fromisoformat(c[-1][0]) - audit.datetime.fromisoformat(c[0][0])).days / 365.25
            cc = (c[-1][1] / 3e6) ** (1 / yrs) - 1; bb = (base_curves[(g, s)][-1][1] / 3e6) ** (1 / yrs) - 1
            Cs.append((cc - bb) * 100)
        if not ok: break
        out[g] = (st.median(Ms), st.median(Ps), st.median(Cs))
    if not ok:
        print(f'{a:<10}{d.parent.parent.name[:9]:<10} (curve dates mismatch or missing; skipped)'); continue
    mf, pf, cf = out['full']; ma, pa, ca = out['A']
    print(f'{a:<10}{("high_base" if "high_base" in str(d) else "round1"):<10}{mf:>+8.2f}{pf:>+8.2f}{ma:>+8.2f}{pa:>+8.2f}{cf:>+10.2f}{ca:>+8.2f}  {rule(mf, ma, cf, ca):<7} {rule(pf, pa, cf, ca)}')
