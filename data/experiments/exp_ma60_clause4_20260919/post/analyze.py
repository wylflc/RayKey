"""Paired readings, §12.1 clause-2 verdicts, clause-4 U qualification, margin plateau table, winner-dose curve, clause-11 attribution."""
import contextlib
import csv
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
EXP = Path(__file__).resolve().parents[1]
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts')); sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw
from ex_winner_symmetry_report import CLAUSE4
GRID = json.loads((EXP / 'grid.json').read_text())
ARMS = [g['arm'] for g in GRID]
MARGIN = {g['arm']: g['margin'] for g in GRID}


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)), lineterminator='\n'); w.writeheader(); w.writerows(rows)


def numeric(row):
    return {**{k: sw._field_value(row, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(row[sw.WIN5_KEY])}


def main():
    completed = json.loads((EXP / 'completed.json').read_text()); assert completed['unchanged_inputs']
    winners = json.loads((EXP / 'winners.json').read_text())
    rows = read(EXP / 'summary_rows.csv')
    groups = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        assert r['start'] not in groups[r['group']][r['arm']], (r['group'], r['arm'], r['start'])
        groups[r['group']][r['arm']][r['start']] = r
    num = {g: {a: {s: numeric(r) for s, r in paths.items()} for a, paths in arms.items()} for g, arms in groups.items()}
    paired, defects = [], []
    for g, arms in num.items():
        for arm in arms:
            if arm == 'BASE':
                continue
            defects += sw.pairing_defects(arms, arm, 'BASE', sw.DEFAULT_STARTS, g)
            for key in (*sw.FIELDS, sw.WIN5_KEY):
                delta = [sw.start_delta(arms[arm][s], arms['BASE'][s], key) for s in sw.DEFAULT_STARTS]
                values = [arms[arm][s][key] for s in sw.DEFAULT_STARTS] if key != sw.WIN5_KEY else []
                paired.append(dict(group=g, arm=arm, metric=key, level_median=st.median(values) if values else '',
                                   base_level_median=st.median(arms['BASE'][s][key] for s in sw.DEFAULT_STARTS) if values else '',
                                   paired_delta_median=st.median(delta) if all(math.isfinite(x) for x in delta) else float('nan'),
                                   positive_starts=sum(x > 0 for x in delta), negative_flips=sum(sw.neg_window_flip(arms[arm][s], arms['BASE'][s]) for s in sw.DEFAULT_STARTS)))
    assert not defects, defects
    write('paired_metrics.csv', paired)
    idx = {(r['group'], r['arm'], r['metric']): r for r in paired}
    union_for = {a: g for g, info in completed['union_groups'].items() for a in info['candidates']}
    pp = lambda g, a, k: 100 * idx[g, a, k]['paired_delta_median']
    decisions = []
    for arm in ARMS[1:]:
        verdict, reasons, _vals = sw.adoption_verdict(num['full'], num['A'], arm)
        u = union_for[arm]
        inferior = []
        for k, scale, good in CLAUSE4:
            d = idx[u, arm, k]['paired_delta_median'] * scale * good
            tolerance, limit = (.005, .033) if scale == 1 else (.15, 1.)
            if d < -tolerance:
                inferior.append(dict(metric=k, delta=round(d, 4), beyond_limit=d < -limit))
        excellent = not inferior or (len(inferior) == 1 and not inferior[0]['beyond_limit'])
        row = dict(arm=arm, margin=MARGIN[arm], verdict=verdict, reasons='；'.join(reasons), U_group=u, U_reused_A=completed['union_groups'][u]['reused_A'],
                   U_excellent=excellent, U_inferior=json.dumps(inferior, ensure_ascii=False))
        for g, alias in (('full', 'full'), ('A', 'A'), (u, 'U')):
            row[f'{alias}_P_pp'] = pp(g, arm, sw.WIN5_KEY); row[f'{alias}_CAGR_pp'] = pp(g, arm, '年化')
            row[f'{alias}_P25_pp'] = pp(g, arm, '滚动5年年化P25'); row[f'{alias}_DD5_pp'] = pp(g, arm, '滚动5年回撤中位')
            row[f'{alias}_MDD_pp'] = pp(g, arm, '最大回撤'); row[f'{alias}_worst5_pp'] = pp(g, arm, '滚动5年年化最差')
            row[f'{alias}_negflips'] = idx[g, arm, '年化']['negative_flips']; row[f'{alias}_P_positive'] = idx[g, arm, sw.WIN5_KEY]['positive_starts']
            row[f'{alias}_CAGR_positive'] = idx[g, arm, '年化']['positive_starts']; row[f'{alias}_turnover_delta'] = idx[g, arm, '年均换手']['paired_delta_median']
            row[f'{alias}_CAGR_level_pct'] = 100 * idx[g, arm, '年化']['level_median']; row[f'{alias}_BASE_CAGR_level_pct'] = 100 * idx[g, arm, '年化']['base_level_median']
        decisions.append(row)
    write('margin_scan.csv', decisions)
    # plateau reading (clause 5): margins whose full-sample main reading is within 0.15pp of the best one
    best = max(decisions, key=lambda r: r['full_P_pp'])
    plateau = [r['margin'] for r in decisions if abs(r['full_P_pp'] - best['full_P_pp']) <= 0.15]
    # dose curve K1/K3/K5/K10 for MA60_1M15 vs BASE
    dose = []
    for k in ('K1', 'K3', 'K5', 'K10'):
        dose.append(dict(dose=k, excluded='/'.join(winners['doses'][k]), n_excluded=len(winners['doses'][k]),
                         P_pp=pp(k, 'MA60_1M15', sw.WIN5_KEY), CAGR_pp=pp(k, 'MA60_1M15', '年化'), P25_pp=pp(k, 'MA60_1M15', '滚动5年年化P25'),
                         DD5_pp=pp(k, 'MA60_1M15', '滚动5年回撤中位'), MDD_pp=pp(k, 'MA60_1M15', '最大回撤'), negflips=idx[k, 'MA60_1M15', '年化']['negative_flips'],
                         P_positive=idx[k, 'MA60_1M15', sw.WIN5_KEY]['positive_starts'], CAGR_positive=idx[k, 'MA60_1M15', '年化']['positive_starts'],
                         BASE_CAGR_level_pct=100 * idx[k, 'MA60_1M15', '年化']['base_level_median'], ARM_CAGR_level_pct=100 * idx[k, 'MA60_1M15', '年化']['level_median']))
    sign = lambda x: (x > 0.15) - (x < -0.15)   # clause-5 noise band; 0 = 噪声级
    same_sign = {key: len({sign(r[key]) for r in dose} - {0}) <= 1 and all(sign(r[key]) != 0 for r in dose) for key in ('P_pp', 'CAGR_pp')}
    write('dose_curve.csv', dose)
    # clause 11: top-3 share of the full-sample anchor-start delta for M15
    anchor = {a: groups['full'][a][sw.EX5_ANCHOR_START]['tag'] for a in ('BASE', 'MA60_1M15')}
    cb = json.loads((EXP / 'contrib' / f"{anchor['BASE']}.json").read_text()); ca = json.loads((EXP / 'contrib' / f"{anchor['MA60_1M15']}.json").read_text())
    dcode = {c: ca.get(c, 0.0) - cb.get(c, 0.0) for c in set(ca) | set(cb)}
    total = sum(dcode.values()); ordered = sorted(dcode.items(), key=lambda kv: -abs(kv[1]))
    top3 = ordered[:3]
    attribution = dict(total_delta=total, top3=[(c, v) for c, v in top3], top3_net_share=(sum(v for _c, v in top3) / total) if total else float('nan'),
                       top3_momentum_share=sum(abs(v) for _c, v in top3) / sum(abs(v) for v in dcode.values()) if dcode else float('nan'), codes_moved=sum(1 for v in dcode.values() if abs(v) > 1e-9))
    # clause 12: family arm count (MS* arms in the ledger index + this batch's new arms)
    index = read(ROOT / 'data/backtest/scan_arms_index.csv')
    ms_arms = {r['臂名'] for r in index if r['臂名'].startswith('MS') and r['台账'] == 'current'}
    new_arms = {'MS' + a for a in ARMS[1:]} - ms_arms
    family = dict(registered_before=sorted(ms_arms), new_this_batch=sorted(new_arms), total_after_registration=len(ms_arms | new_arms))
    # standard report (full + A) for the record
    combined = sw.metric_header() + '\n#MARKET|a\n#EX5|fixed|' + ','.join(winners['A']) + '\n'
    for g in ('full', 'A'):
        for arm in ARMS:
            for s in sw.DEFAULT_STARTS:
                r = groups[g][arm][s]; label = ('EX5:' if g == 'A' else '') + arm
                combined += '|'.join([label, s] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n'
                combined += f"#WIN5|{label}|{s}|{r[sw.WIN5_KEY]}\n"
    (EXP / 'sweep_full_A.txt').write_text(combined)
    with (EXP / 'report_full_A.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(EXP / 'sweep_full_A.txt', 'MA60_1 换仓边际 0.10～0.20 重扫（§12.1 第 4 款①）对当前 BASE')
    verification = dict(arms=len(ARMS), complete_pairing=True, zero_negative_cash=all(r['负现金日数'] == '0' for r in rows), rows=len(rows),
                        executed_paths=completed['executed_paths'], plateau_margins_within_0p15pp_of_best=plateau, best_margin=best['margin'],
                        clause2_pass=[r['arm'] for r in decisions if r['verdict'].startswith('可采纳')], clause2_user_ruling=[r['arm'] for r in decisions if '裁定' in r['verdict']],
                        U_excellent=[r['arm'] for r in decisions if r['U_excellent']], dose_same_sign=same_sign, attribution_M15_anchor=attribution, family=family,
                        production_parameters_changed=False)
    (EXP / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(verification, ensure_ascii=False, indent=2))
    for r in decisions:
        print(f"{r['arm']:<10} full P {r['full_P_pp']:+.2f} CAGR {r['full_CAGR_pp']:+.2f} | A P {r['A_P_pp']:+.2f} CAGR {r['A_CAGR_pp']:+.2f} | U P {r['U_P_pp']:+.2f} CAGR {r['U_CAGR_pp']:+.2f} | {r['verdict']} | U优秀 {r['U_excellent']}")
    for r in dose:
        print(f"{r['dose']:<4} n={r['n_excluded']:<2} P {r['P_pp']:+.2f} CAGR {r['CAGR_pp']:+.2f} P25 {r['P25_pp']:+.2f} DD5 {r['DD5_pp']:+.2f} flips {r['negflips']}")


if __name__ == '__main__':
    main()
