"""OI-207 银行估值多方法检验（preregister.md）。

    python3 bank_methods.py prepare    # 冻结银行保险行：覆盖前逐日状态、带文件、生产逐日状态，及利率表与除权表的哈希
    python3 bank_methods.py methods    # rebuild_bank_bands.py 各模式 → states/<代号>.csv；核对 D0 与生产逐位一致
    python3 bank_methods.py analyze    # R1～R5 → results.json、report.md
"""
import bisect
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))

INPUTS = EXP / 'inputs'
STATES = EXP / 'states'
MODES = {'D0': 'divspread:0.02', 'RI10': 'ri:0.10', 'RIP': 'ri:peer', 'DDM10': 'ddm:0.10', 'DDMP': 'ddm:peer',
         'PBP': 'peer', 'PBH': 'pbhist'}
METHODS = ('D0', 'D1', 'E0', 'RI10', 'RIP', 'DDM10', 'DDMP', 'PBP', 'PBH')
INSURERS = ('601318', '601628', '601601', '601336', '601319')
BIG4 = ('601398', '601288', '601988', '601939')
CASES = {'600036': '招商银行', '002142': '宁波银行'}
LINE = 1.0670
HORIZONS = (1, 2, 3)
BOOT = 1000
START = '2010-01'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 22), b''):
            h.update(block)
    return h.hexdigest()


def financial_codes() -> dict:
    from divspread_names import is_divspread_financial
    out = {}
    with (ROOT / 'data/raw/a_share_securities.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            code = r['security_code'].zfill(6)
            if is_divspread_financial(code, r['security_name']):
                out[code] = r['security_name']
    return out


def prepare():
    INPUTS.mkdir(exist_ok=True)
    codes = financial_codes()
    for src, dst in (('data/processed/roic_daily_raw.csv', 'bank_daily_raw.csv'), ('data/processed/roic_bands.csv', 'bank_bands.csv'),
                     ('data/processed/a_share_daily_states_adopted.csv', 'bank_states_production.csv')):
        n = 0
        with (ROOT / src).open(encoding='utf-8', newline='') as fi, (INPUTS / dst).open('w', encoding='utf-8', newline='') as fo:
            fo.write(fi.readline())
            for line in fi:
                if line[:6] in codes:
                    fo.write(line); n += 1
        print('FROZEN', dst, n, flush=True)
    shutil.copyfile(ROOT / 'data/reference/cost_of_equity_inputs.csv', INPUTS / 'cost_of_equity_inputs.csv')
    manifest = dict(revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    job_id=os.getenv('SLURM_JOB_ID'), codes=codes,
                    sources={p: digest(ROOT / p) for p in ('data/processed/roic_daily_raw.csv', 'data/processed/roic_bands.csv',
                                                          'data/processed/a_share_daily_states_adopted.csv',
                                                          'data/reference/cost_of_equity_inputs.csv',
                                                          'data/raw/corporate_actions/a_share_corporate_actions.csv')})
    (EXP / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + '\n')


def run_mode(item):
    label, mode = item
    STATES.mkdir(exist_ok=True)
    out = STATES / f'{label}.csv'
    with (EXP / f'mode_{label}.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT / 'scripts/rebuild_bank_bands.py'), mode, str(out),
                        str(INPUTS / 'bank_daily_raw.csv'), str(INPUTS / 'bank_bands.csv')],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    return label


def methods():
    with ProcessPoolExecutor(max_workers=len(MODES)) as pool:
        for label in pool.map(run_mode, MODES.items()):
            print('DONE', label, flush=True)
    a = (STATES / 'D0.csv').read_bytes()
    b = (INPUTS / 'bank_states_production.csv').read_bytes()
    same = a == b
    diffs = 0
    if not same:
        with (STATES / 'D0.csv').open() as fa, (INPUTS / 'bank_states_production.csv').open() as fb:
            ra, rb = list(csv.DictReader(fa)), list(csv.DictReader(fb))
        ka = {(r['security_code'], r['date']): r['valuation_ratio'] for r in ra}
        kb = {(r['security_code'], r['date']): r['valuation_ratio'] for r in rb}
        diffs = sum(1 for k in ka.keys() | kb.keys() if ka.get(k) != kb.get(k))
    (EXP / 'd0_check.json').write_text(json.dumps(dict(identical_bytes=same, pv_differences=diffs), indent=1) + '\n')
    print('D0 与生产逐位一致' if same else f'D0 与生产 P/V 不同 {diffs} 行', flush=True)


# ---------------- analyze ----------------

def month_end_pv(path: Path) -> dict:
    """(代码, 年月) → (当月最后一行日期, P/V 或 None)。"""
    out = {}
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.reader(f)
        h = next(reader)
        ic, idt, ipv = h.index('security_code'), h.index('date'), h.index('valuation_ratio')
        for row in reader:
            if row[idt][:7] < START:
                continue
            try:
                pv = float(row[ipv])
            except ValueError:
                pv = None
            key = (row[ic], row[idt][:7])
            if key not in out or row[idt] >= out[key][0]:
                out[key] = (row[idt], pv if pv is not None and pv > 0 else None)
    return out


def rf_series():
    rows = []
    with (INPUTS / 'cost_of_equity_inputs.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            try:
                rows.append((r['observed_on'], float(r['risk_free_rate'])))
            except (TypeError, ValueError):
                pass
    rows.sort()
    return [d for d, _ in rows], [v for _, v in rows]


def spans():
    out = defaultdict(list)
    with (ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            out[r['security_code'].zfill(6)].append((r['effective_from'], r.get('effective_to') or '9999-12-31'))
    return out


def daily_pv(path: Path) -> dict:
    """(代码, 日期) → P/V（无效记 None）；银行保险行文件小，整表载入。"""
    out = {}
    with path.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            try:
                pv = float(r['valuation_ratio'])
            except ValueError:
                pv = None
            out[(r['security_code'], r['date'])] = pv if pv is not None and pv > 0 else None
    return out


def observations():
    """观测日 = 覆盖前逐日状态（全部银行行都在）的当月最后一行；各方法取同一日的 `P/V`（该方法丢弃的行记无法估值）。"""
    import build_historical_valuation_bands as bhv
    from moat_param_lab import forward_annualized, total_return_index
    codes = json.loads((EXP / 'manifest.json').read_text())['codes']
    ends = month_end_pv(INPUTS / 'bank_daily_raw.csv')
    pv = {m: daily_pv(STATES / f'{m}.csv') for m in MODES}
    rfd, rfv = rf_series()
    sp = spans()
    actions = bhv.load_actions()
    rows = []
    for code in sorted(codes):
        prices = bhv.load_ohlcv(code)
        if not prices:
            continue
        days = [d for d, _ in prices]
        tr = total_return_index(prices, actions.get(code, []))
        for key in sorted(k for k in ends if k[0] == code):
            day, e0 = ends[key]
            if day not in tr:
                continue
            row = dict(code=code, name=codes[code], month=key[1], date=day, insurer=code in INSURERS,
                       panel=any(a <= day <= b for a, b in sp.get(code, ())))
            for m in MODES:
                row[m] = pv[m].get((code, day))
            row['E0'] = e0
            i = bisect.bisect_right(rfd, day) - 1
            rf = rfv[i] if i >= 0 else None
            row['D1'] = row['D0'] * (0.07 / 1.03) / (rf + 0.02) if row['D0'] and rf is not None else None
            for h in HORIZONS:
                row[f'f{h}'] = forward_annualized(tr, days, day, h)
            rows.append(row)
    return rows


def spearman(x, y):
    import numpy as np
    from scipy.stats import rankdata
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def nw_t(series, lag):
    import numpy as np
    x = np.asarray(series, float)
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for k in range(1, min(lag, n - 1) + 1):
        var += 2 * (1 - k / (lag + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(var / n)) if var > 0 else None


def r1(rows, panel_only=False):
    out = {}
    banks = [r for r in rows if not r['insurer'] and (r['panel'] or not panel_only)]
    for h in HORIZONS:
        by_month = defaultdict(list)
        for r in banks:
            if r[f'f{h}'] is not None:
                by_month[r['month']].append(r)
        ics = {m: {} for m in METHODS}
        for month, rs in sorted(by_month.items()):
            for m in METHODS:
                v = [(r[m], r[f'f{h}']) for r in rs if r[m]]
                if len(v) >= 10:
                    ics[m][month] = spearman([math.log(a) for a, _ in v], [b for _, b in v])
        entry = {}
        for m in METHODS:
            s = list(ics[m].values())
            entry[m] = dict(months=len(s), mean_ic=sum(s) / len(s) if s else None, nw_t=nw_t(s, 12 * h),
                            negative_share=sum(x < 0 for x in s) / len(s) if s else None)
            if m != 'D0':
                common = sorted(ics[m].keys() & ics['D0'].keys())
                d = [ics[m][k] - ics['D0'][k] for k in common]
                entry[m]['vs_D0'] = dict(months=len(d), mean=sum(d) / len(d) if d else None, nw_t=nw_t(d, 12 * h))
        out[f'{h}y'] = entry
    return out


def r2(rows, rng_seed=20260928):
    import numpy as np
    src = ROOT / 'data/experiments/exp_oi205b_20260928/cache/fairness_observations.csv'
    if not src.exists():
        return dict(status='缺非金融观测（OI-205 重测公允性作业未完成），顺延')
    nonfin = []
    with src.open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            try:
                pv, f3 = float(r['pv_C']), float(r['f3'])
            except ValueError:
                continue
            if pv > 0:
                nonfin.append(dict(code=r['code'], month=r['month'], panel=r['panel'] == 'True', pv=pv, f3=f3))
    rng = np.random.default_rng(rng_seed)
    out = {}
    for universe in ('面板', '全部'):
        base = [r for r in nonfin if r['panel'] or universe == '全部']
        for m in METHODS:
            banks = [dict(code=r['code'], month=r['month'], pv=r[m], f3=r['f3'])
                     for r in rows if not r['insurer'] and r[m] and r['f3'] is not None and (r['panel'] or universe == '全部')]
            sample = [dict(r, bank=0.0) for r in base if 0.2 <= r['pv'] <= 5] + [dict(r, bank=1.0) for r in banks if 0.2 <= r['pv'] <= 5]
            months = {mm: i for i, mm in enumerate(sorted({r['month'] for r in sample}))}
            codes = {c: i for i, c in enumerate(sorted({r['code'] for r in sample}))}
            y = np.log1p(np.array([r['f3'] for r in sample]))
            x = np.log(np.array([r['pv'] for r in sample]))
            z = np.array([r['bank'] for r in sample])
            t = np.array([months[r['month']] for r in sample])
            s = np.array([codes[r['code']] for r in sample])

            def fit(w):
                tot = np.bincount(t, weights=w)
                safe = np.where(tot > 0, tot, 1.0)
                cols = [c - (np.bincount(t, weights=w * c) / safe)[t] for c in (y, x, z)]
                X = np.column_stack(cols[1:])
                Xw = X * w[:, None]
                return np.linalg.solve(X.T @ Xw, Xw.T @ cols[0])
            beta = fit(np.ones(len(y)))
            draws = []
            for _ in range(BOOT):
                w = np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float)[s]
                draws.append(fit(w))
            draws = np.array(draws)
            banks_pv = np.array([r['pv'] for r in banks])
            out[f'{universe}:{m}'] = dict(n_banks=len(banks), n_nonfin=int((z == 0).sum()), b=float(beta[0]), c=float(beta[1]),
                                          c_ci=[float(np.percentile(draws[:, 1], 5)), float(np.percentile(draws[:, 1], 95))],
                                          bank_pv_median=float(np.median(banks_pv)) if len(banks_pv) else None,
                                          bank_zone_share=float((banks_pv <= LINE).mean()) if len(banks_pv) else None)
    return out


def r3(rows):
    by = defaultdict(dict)
    for r in rows:
        by[r['month']][r['code']] = r
    out = {}
    for code, name in CASES.items():
        table = []
        for year in range(2012, 2024):
            month = f'{year}-12'
            cell = by.get(month, {})
            if code not in cell:
                continue
            entry = dict(month=month)
            for h in HORIZONS:
                big = sorted(cell[b][f'f{h}'] for b in BIG4 if b in cell and cell[b][f'f{h}'] is not None)
                f = cell[code][f'f{h}']
                entry[f'rel_f{h}'] = (f - big[len(big) // 2] if len(big) % 2 else f - (big[len(big) // 2 - 1] + big[len(big) // 2]) / 2) \
                    if big and f is not None else None
            for m in METHODS:
                big = sorted(cell[b][m] for b in BIG4 if b in cell and cell[b][m])
                own = cell[code][m]
                if big and own:
                    med = big[len(big) // 2] if len(big) % 2 else (big[len(big) // 2 - 1] + big[len(big) // 2]) / 2
                    entry[m] = math.log(own / med)
                else:
                    entry[m] = None
            table.append(entry)
        summary = {}
        for m in METHODS:
            for h in HORIZONS:
                pairs = [(e[m], e[f'rel_f{h}']) for e in table if e[m] is not None and e[f'rel_f{h}'] is not None]
                agree = sum(1 for a, b in pairs if (a < 0) == (b > 0))
                corr = None
                if len(pairs) >= 4:
                    import numpy as np
                    corr = float(np.corrcoef([a for a, _ in pairs], [b for _, b in pairs])[0, 1])
                summary[f'{m}:{h}y'] = dict(years=len(pairs), sign_agree=agree, corr=corr)
        out[code] = dict(name=name, table=table, summary=summary)
    return out


def r4(rows):
    import numpy as np
    labels = {}
    fin = set(json.loads((EXP / 'manifest.json').read_text())['codes'])
    with (ROOT / 'data/backtest/opportunity_trap_labels_v1.csv').open(encoding='utf-8', newline='') as f:
        for r in csv.DictReader(f):
            if r['panel'] == 'True' and r['label'] and r['code'] in fin:
                labels[(r['code'], r['month'])] = r['label']
    keyed = {(r['code'], r['month']): r for r in rows if not r['insurer']}
    items = [(k, lab, keyed[k]) for k, lab in labels.items() if k in keyed]
    codes = sorted({k[0] for k, _, _ in items})
    idx = {c: i for i, c in enumerate(codes)}
    rng = np.random.default_rng(20260928)
    out = dict(months=len(items), stocks=len(codes), opp=sum(l == '机会' for _, l, _ in items), trap=sum(l == '陷阱' for _, l, _ in items))

    def rates(m, w):
        tot = dict(n=0.0, zone=0.0, opp=0.0, trap=0.0, oz=0.0, tz=0.0)
        for (code, _), lab, r in items:
            wt = w[idx[code]]
            zone = r[m] is not None and r[m] <= LINE
            tot['n'] += wt; tot['zone'] += wt * zone
            tot['opp'] += wt * (lab == '机会'); tot['trap'] += wt * (lab == '陷阱')
            tot['oz'] += wt * (lab == '机会' and zone); tot['tz'] += wt * (lab == '陷阱' and zone)
        d = lambda a, b: a / b if b else float('nan')
        return dict(zone_share=d(tot['zone'], tot['n']), opp_capture=d(tot['oz'], tot['opp']), zone_trap_share=d(tot['tz'], tot['zone']),
                    lift_opp=d(d(tot['oz'], tot['zone']), d(tot['opp'], tot['n'])), lift_trap=d(d(tot['tz'], tot['zone']), d(tot['trap'], tot['n'])))
    one = np.ones(len(codes))
    draws = [np.bincount(rng.integers(0, len(codes), len(codes)), minlength=len(codes)).astype(float) for _ in range(200)]
    for m in METHODS:
        point = rates(m, one)
        boot = [rates(m, w) for w in draws]
        out[m] = {k: dict(point=v, ci=[float(np.nanpercentile([b[k] for b in boot], 5)), float(np.nanpercentile([b[k] for b in boot], 95))])
                  for k, v in point.items()}
    return out


def r5(rows):
    table = []
    for r in rows:
        if r['insurer'] and r['month'][5:] == '12':
            table.append({k: r[k] for k in ('code', 'name', 'month', 'f3', *METHODS)})
    return table


def analyze():
    rows = observations()
    with (EXP / 'observations.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    results = dict(observations=len(rows), banks=len({r['code'] for r in rows if not r['insurer']}),
                   coverage={m: sum(1 for r in rows if r[m] and not r['insurer']) for m in METHODS},
                   R1=r1(rows), R1_panel=r1(rows, panel_only=True), R2=r2(rows), R3=r3(rows), R4=r4(rows), R5=r5(rows))
    (EXP / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float) + '\n')
    print(json.dumps({k: results[k] for k in ('observations', 'banks', 'coverage')}, ensure_ascii=False))
    for h in ('1y', '2y', '3y'):
        print(h, {m: round(v['mean_ic'], 3) if v['mean_ic'] is not None else None for m, v in results['R1'][h].items()})


if __name__ == '__main__':
    {'prepare': prepare, 'methods': methods, 'analyze': analyze}[sys.argv[1]]()
