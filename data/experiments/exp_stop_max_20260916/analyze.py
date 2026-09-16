"""Validate complete paired paths, preserve full summaries and register this experiment."""
import csv
import json
import math
import os
import statistics as st
import sys
from run import EXP, ROOT, save, summary, sw

sys.path.insert(0, str(ROOT / 'scripts/experimental'))
from ex_winner_symmetry_report import CLAUSE4


def write(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def main():
    done = json.loads((EXP / 'completed.json').read_text())
    assert done['inputs_unchanged']
    winners = json.loads((EXP / 'winner_sets.json').read_text())
    scans = sw.load_scan(EXP / 'sweep_full_A.txt')[0]
    groups = {'full': scans[''], 'A': scans['EX5:']}
    if winners['U_reused_A']:
        groups['U'] = groups['A']
    else:
        groups['U'] = sw.load_scan(EXP / 'sweep_U.txt')[0]['EX5:']
    rows, metrics, anchors, differences = [], [], [], []
    reference_path = EXP.parent / 'exp_oi180_189_20260914/summary_rows.csv'
    with reference_path.open() as f:
        reference = {(r['group'], r['start']): r for r in csv.DictReader(f)
                     if r['arm'] == 'SIGNAL' and r['bp'] == '0'}
    for group, arms in groups.items():
        assert not sw.pairing_defects(arms, 'STOPMAX', 'BASE', sw.DEFAULT_STARTS, group)
        for arm in ('BASE', 'STOPMAX'):
            for start in sw.DEFAULT_STARTS:
                tag = sw.summary_tag(arm, start, '' if group == 'full' else 'excluded')
                cache = EXP / 'cache'
                if group != 'U' or winners['U_reused_A']:
                    cache /= 'full_A'
                row = summary(cache / f'summary_{tag}.csv')
                assert row['计量版本'] == sw.METRIC_VERSION
                assert row['负现金日数'] == '0'
                assert math.isclose(float(row['期末资产']) / 3_000_000 - 1, float(row['总收益']), abs_tol=1e-9)
                rows.append(dict(group=group, arm=arm, start=start, **row))
                if group in ('full', 'A') and arm == 'BASE':
                    old = reference[group, start]
                    for k in (*sw.FIELDS, sw.WIN5_KEY):
                        if old[k] != row[k]:
                            differences.append(dict(group=group, start=start, metric=k, old=old[k], current=row[k]))
                if start in ('2009-11-01', '2011-11-01'):
                    anchors.append(dict(group=group, arm=arm, start=start, end=row['末次净值日'],
                        final_equity=float(row['期末资产']), total_return_pct=100 * float(row['总收益']),
                        cagr_pct=100 * float(row['年化']), mdd_pct=100 * float(row['最大回撤']),
                        buys=int(row['买入笔数']), sells=int(row['卖出笔数']),
                        average_holding_days=float(row['平均持有天数'])))
            for key in (*sw.FIELDS, sw.WIN5_KEY):
                delta = [sw.start_delta(arms[arm][s], arms['BASE'][s], key) for s in sw.DEFAULT_STARTS]
                level = [arms[arm][s][key] for s in sw.DEFAULT_STARTS] if key != sw.WIN5_KEY else []
                metrics.append(dict(group=group, arm=arm, metric=key,
                    level_median=st.median(level) if level else '', paired_delta_median=st.median(delta),
                    positive_starts=sum(x > 0 for x in delta), finite_starts=sum(math.isfinite(x) for x in delta)))
    write('summary_rows.csv', rows)
    write('paired_metrics.csv', metrics)
    write('anchors.csv', anchors)
    save('baseline_comparison.json', dict(reference=str(reference_path.relative_to(ROOT)),
        fields_checked=28 * (len(sw.FIELDS) + 1), differences=differences))
    verdict, reasons, values = sw.adoption_verdict(groups['full'], groups['A'], 'STOPMAX')
    idx = {(r['group'], r['arm'], r['metric']): r for r in metrics}
    inferior = []
    for key, scale, good in CLAUSE4:
        delta = idx['U', 'STOPMAX', key]['paired_delta_median'] * scale * good
        noise, limit = (.005, .033) if scale == 1 else (.15, 1.)
        if delta < -noise:
            inferior.append(dict(metric=key, delta=delta, beyond_limit=delta < -limit))
    excellent = not inferior or (len(inferior) == 1 and not inferior[0]['beyond_limit'])
    save('verification.json', dict(complete_pairing=True, zero_negative_cash=True, inputs_unchanged=True,
        paths=done['paths'], baseline_reference_differences=len(differences), verdict=verdict,
        reasons=reasons, readings=values, U_excellent=excellent, U_inferior=inferior,
        production_parameters_changed=False))
    for path in EXP.glob('report_*.txt'):
        path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
    print(json.dumps(dict(verdict=verdict, reasons=reasons, U_excellent=excellent,
                         baseline_reference_differences=len(differences)), ensure_ascii=False))


def register():
    import clean_derived_artifacts as ledger
    verification = json.loads((EXP / 'verification.json').read_text())
    assert verification['complete_pairing'] and verification['inputs_unchanged']
    with (EXP / 'summary_rows.csv').open() as f:
        rows = list(csv.DictReader(f))
    reused = json.loads((EXP / 'winner_sets.json').read_text())['U_reused_A']
    out = EXP / 'cache/register'
    out.mkdir(exist_ok=True)
    for r in rows:
        if r['group'] == 'U' and reused:
            continue
        # Dedicated batch tags protect all previously registered BASE rows.
        tag = (f"SMAX20260916_{r['group']}{r['arm']}{r['start'].replace('-', '')}"
               + ('ex5' if r['group'] != 'full' else ''))
        clean = {k: v for k, v in r.items() if k not in ('group', 'arm', 'start')}
        clean['策略'] = clean['策略'].rsplit('_', 1)[0] + '_' + tag
        with (out / f'summary_{tag}.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(clean))
            w.writeheader()
            w.writerow(clean)
    def read_ledger():
        with ledger.MERGED.open() as f:
            return {(r['扫描标签'], r['策略'], r['计量版本']): r for r in csv.DictReader(f)}
    before = read_ledger()
    with os.scandir(out) as entries:
        ledger.write_ledger(list(entries))
    after = read_ledger()
    assert all(after[k] == v for k, v in before.items()), 'old ledger rows changed'
    save('registration.json', dict(summary_rows=56 if reused else 84,
         added_keys=len(after) - len(before), old_rows_unchanged=True,
         entry_point='clean_derived_artifacts.write_ledger'))
    print('REGISTERED', len(after) - len(before), 'new rows')


if __name__ == '__main__':
    register() if '--register' in sys.argv else main()
