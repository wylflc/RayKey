"""Daily rank size/cutoff and mechanical trend eligibility, independent of portfolio cash."""
import bisect
from collections import defaultdict
import csv
from fractions import Fraction
import json
from pathlib import Path
import statistics as st
import sys

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_valuation_strategy as bt
import sweep_backtest_configs as sw


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n'); w.writeheader(); w.writerows(rows)


def quantile(values, p):
    a = sorted(values)
    if not a: return ''
    i = (len(a)-1)*p; lo = int(i); hi = min(len(a)-1, lo+1)
    return a[lo] + (a[hi]-a[lo])*(i-lo)


def audit(exclusion_groups):
    grid = json.loads((EXP / 'grid.json').read_text())
    panel = ROOT / 'data/processed/pit_attention/panel_moat_bank_v6b.csv'
    universe = bt.load_universe(panel)
    uni_dates = [d for d, _ in universe]
    codes = {c for _, members in universe for c in members}
    states = bt.load_states(EXP.parent / 'exp_oi168_wc_20260909/val/WCOP/states_base.csv', codes)
    prices = bt.load_prices(codes); actions = bt.load_actions()
    mas = {c: bt.adjusted_moving_averages(series, actions.get(c, {}), (20, 60)) for c, series in prices.items()}
    days = sorted(d for d in states if d >= min(sw.DEFAULT_STARTS))
    audit_checks = 0
    for group, excluded in exclusion_groups.items():
        excluded = set(excluded); records = []
        for signal_day, exec_day in zip(days, days[1:]):
            def members(d):
                i = bisect.bisect_right(uni_dates, d)-1
                return universe[i][1] - excluded if i >= 0 else set()
            signal_members, exec_members = members(signal_day), members(exec_day)
            pool = [r for r in states[signal_day] if r[0] in signal_members]
            valid, n = bt.top_fraction_candidates(pool, 1.0)
            for config in grid:
                q = config['value']; arm = config['arm']
                if config['kind'] == 'fraction':
                    fraction = Fraction(str(q)); k = n * fraction.numerator // fraction.denominator
                    selected = valid[:k]
                    assert not n or 0 <= q-len(selected)/n < 1/n + 1e-12
                    cutoff = selected[-1][3] if selected else ''
                    # Check the runtime selector against the rank-prefix audit.
                    if signal_day == days[0]:
                        selected2, n2 = bt.top_fraction_candidates(pool, fraction)
                        assert selected2 == selected and n2 == n
                else:
                    selected = [r for r in valid if r[3] <= q]; cutoff = q
                tradable = [r for r in selected if r[0] in exec_members and prices.get(r[0], {}).get(exec_day)]
                new_count = held_count = 0
                for code, close, value, pv in tradable:
                    ma = mas.get(code, {}).get(signal_day, {})
                    if 20 in ma and 60 in ma and ma[20] > ma[60]:
                        held_count += 1
                        new_count += close > ma[20]
                records.append({'group': group, 'arm': arm, 'kind': config['kind'], 'value': q,
                    'signal_day': signal_day, 'execution_day': exec_day, 'year': signal_day[:4],
                    'denominator': n, 'selected': len(selected), 'share': len(selected)/n if n else '',
                    'pv_cutoff': cutoff, 'execution_members_and_price': len(tradable),
                    'potential_new_entry_count': new_count, 'potential_addon_count': held_count})
                audit_checks += 1
        write_csv(EXP / f'daily_selection_{group}.csv', records)
        bins = defaultdict(list)
        for r in records:
            bins[(r['arm'], 'ALL')].append(r); bins[(r['arm'], r['year'])].append(r)
        summary = []
        for (arm, year), bucket in bins.items():
            n = sum(r['denominator'] for r in bucket)
            thresholds = [r['pv_cutoff'] for r in bucket if r['pv_cutoff'] != '']
            shares = [r['share'] for r in bucket if r['share'] != '']
            summary.append({'group': group, 'arm': arm, 'year': year, 'signal_days': len(bucket),
                'company_days': n, 'selected_company_days': sum(r['selected'] for r in bucket),
                'weighted_share': sum(r['selected'] for r in bucket)/n if n else '',
                'daily_share_min': min(shares, default=''), 'daily_share_median': st.median(shares) if shares else '',
                'daily_share_max': max(shares, default=''), 'cutoff_min': min(thresholds, default=''),
                'cutoff_p10': quantile(thresholds, .1), 'cutoff_median': quantile(thresholds, .5),
                'cutoff_p90': quantile(thresholds, .9), 'cutoff_max': max(thresholds, default=''),
                'days_cutoff_above_base': sum(v > 1.0454 for v in thresholds),
                'execution_members_and_price': sum(r['execution_members_and_price'] for r in bucket),
                'potential_new_entry_company_days': sum(r['potential_new_entry_count'] for r in bucket),
                'potential_addon_company_days': sum(r['potential_addon_count'] for r in bucket)})
        write_csv(EXP / f'selection_summary_{group}.csv', summary)
    print(f'SELECTION AUDIT COMPLETE: {audit_checks} group/config/signal-day observations.', flush=True)


if __name__ == '__main__': audit({'full': []})
