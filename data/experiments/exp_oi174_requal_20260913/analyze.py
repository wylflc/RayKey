"""Strict paired readings, §12.1 clause-2 verdicts (post OI-172/173 implementation) and clause-4 U qualification."""
from collections import defaultdict
import contextlib
import csv
import json
import math
import statistics as st
import sys
from prepare import EXP, ROOT, save, sw
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
from ex_winner_symmetry_report import CLAUSE4  # noqa: E402


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader(); w.writerows(rows)


def numeric(row):
    return {**{k: sw._field_value(row, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(row[sw.WIN5_KEY])}


def main():
    verification = json.loads((EXP / 'verification.json').read_text())
    assert verification['inputs_unchanged'] and verification['baseline_paths'] == 28
    rows = read(EXP / 'summary_rows.csv')
    groups = defaultdict(lambda: defaultdict(dict))
    for r in rows:
        assert r['start'] not in groups[r['group']][r['arm']]
        groups[r['group']][r['arm']][r['start']] = r
    numeric_groups, paired, anchors, defects = {}, [], [], []
    for group, arms in groups.items():
        numeric_groups[group] = {arm: {s: numeric(r) for s, r in paths.items()} for arm, paths in arms.items()}
        for arm in arms:
            d = sw.pairing_defects(numeric_groups[group], arm, 'BASE', sw.DEFAULT_STARTS, group)
            defects += d
            for start, r in arms[arm].items():
                daily = read(EXP / 'nav' / f"{r['nav_tag']}.csv")
                assert all(math.isfinite(float(x['net_equity'])) and float(x['net_equity']) > 0 for x in daily)
                base_tag = arms['BASE'][start]['nav_tag']
                assert [x['date'] for x in daily] == [x['date'] for x in read(EXP / 'nav' / f'{base_tag}.csv')], (group, arm, start)
            for key in (*sw.FIELDS, sw.WIN5_KEY):
                a, b = numeric_groups[group][arm], numeric_groups[group]['BASE']
                delta = [sw.start_delta(a[s], b[s], key) for s in sw.DEFAULT_STARTS]
                values = [a[s][key] for s in sw.DEFAULT_STARTS] if key != sw.WIN5_KEY else []
                paired.append(dict(group=group, arm=arm, metric=key, level_median=st.median(values) if values else '',
                                   paired_delta_median=st.median(delta) if not any(x != x for x in delta) else float('nan'),
                                   positive_starts=sum(x > 0 for x in delta), finite_delta_starts=sum(math.isfinite(x) for x in delta)))
            for start in ('2009-11-01', '2011-11-01'):
                r, b = arms[arm][start], arms['BASE'][start]
                anchors.append(dict(group=group, arm=arm, start=start, cagr_pct=100 * float(r['年化']),
                                    cagr_delta_pp=100 * (float(r['年化']) - float(b['年化'])), mdd_pct=100 * float(r['最大回撤']),
                                    mdd_delta_pp=100 * (float(r['最大回撤']) - float(b['最大回撤']))))
    assert not defects, defects
    write('paired_metrics.csv', paired); write('anchors.csv', anchors)
    idx = {(r['group'], r['arm'], r['metric']): r for r in paired}
    union_for = {a: g for g, info in verification['union_groups'].items() for a in info['candidates']}
    decisions = []
    for spec in json.loads((EXP / 'grid.json').read_text()):
        arm = spec['arm']
        verdict, reasons, vals = sw.adoption_verdict(numeric_groups['full'], numeric_groups['A'], arm)
        u = union_for.get(arm, 'A')
        inferior = []
        for k, scale, good in CLAUSE4:
            d = idx[u, arm, k]['paired_delta_median'] * scale * good
            tolerance, limit = (.005, .033) if scale == 1 else (.15, 1.)
            if d < -tolerance:
                inferior.append(dict(metric=k, delta=d, beyond_limit=d < -limit))
        excellent = not inferior or (len(inferior) == 1 and not inferior[0]['beyond_limit'])
        row = dict(arm=arm, kind=spec['kind'], verdict=verdict, reasons='；'.join(reasons), U=u, U_excellent=excellent,
                   U_inferior=json.dumps(inferior, ensure_ascii=False))
        for g in ('full', 'A', u):
            alias = 'U' if g == u and g not in ('full', 'A') else g
            for short, k in (('cagr', '年化'), ('P', sw.WIN5_KEY), ('mdd', '最大回撤'), ('p25', '滚动5年年化P25'),
                             ('worst5', '滚动5年年化最差'), ('roll5dd', '滚动5年回撤中位'), ('exposure', '平均仓位')):
                row[f'{alias}_{short}_delta_pp'] = 100 * idx[g, arm, k]['paired_delta_median']
                if k != sw.WIN5_KEY:
                    row[f'{alias}_{short}_level_pct'] = 100 * idx[g, arm, k]['level_median']
        if u == 'A':
            row.update({k.replace('A_', 'U_', 1): v for k, v in list(row.items()) if k.startswith('A_')})
        for start in ('2009-11-01', '2011-11-01'):
            a = next(r for r in anchors if r['group'] == 'full' and r['arm'] == arm and r['start'] == start)
            row[f'anchor{start[:4]}_cagr_pct'] = a['cagr_pct']; row[f'anchor{start[:4]}_mdd_pct'] = a['mdd_pct']
        decisions.append(row)
    decisions.sort(key=lambda r: r['full_cagr_delta_pp'], reverse=True)
    write('decisions.csv', decisions)
    a = verification['union_groups'] and sorted(json.loads((EXP / 'winner_sets.json').read_text())[decisions[0]['arm'] if decisions[0]['arm'] != 'BASE' else decisions[1]['arm']]['A'])
    combined = sw.metric_header() + '\n#MARKET|a\n#EX5|fixed|' + ','.join(a) + '\n'
    for group in ('full', 'A'):
        for arm in [r['arm'] for r in json.loads((EXP / 'grid.json').read_text())]:
            for start in sw.DEFAULT_STARTS:
                r = groups[group][arm][start]
                label = ('EX5:' if group == 'A' else '') + arm
                combined += '|'.join([label, start] + [f'{sw._field_value(r, k):.6f}' for k in sw.FIELDS]) + '\n'
                combined += f"#WIN5|{label}|{start}|{r[sw.WIN5_KEY]}\n"
    (EXP / 'sweep_full_A.txt').write_text(combined)
    with (EXP / 'report_full_A.txt').open('w') as f, contextlib.redirect_stdout(f):
        sw.report(EXP / 'sweep_full_A.txt', 'OI-174 剩余候选对新 BASE 的资格复核')
    rp = EXP / 'report_full_A.txt'
    rp.write_text('\n'.join(x.rstrip() for x in rp.read_text().splitlines()) + '\n')
    qualified = [r['arm'] for r in decisions if r['arm'] != 'BASE' and r['U_excellent']]
    passing = [r['arm'] for r in decisions if r['arm'] != 'BASE' and r['verdict'].startswith('可采纳')]
    save('analysis_verification.json', dict(arms=len(decisions), complete_start_and_window_sets=True, negative_cash_days=0,
         verdict_implementation='sweep_backtest_configs.adoption_verdict (OI-172/173 fixed)', u_excellent=qualified,
         clause2_pass=passing, production_parameters_changed=False))
    print('U 全面优秀：', qualified, '；第 2 款通过：', passing)


if __name__ == '__main__':
    main()
