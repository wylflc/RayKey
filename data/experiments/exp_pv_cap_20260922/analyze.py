"""Strict paired report for the preregistered P/V cap experiment."""
import contextlib
import csv
import json
import statistics as st
import sys
from pathlib import Path

EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts/experimental'))
import sweep_backtest_configs as sw


def clause4(arms, label, ref):
    """Apply §12.1.4 literally, including average exposure in STANDARD_SET.

    The historical slippage helper omits exposure as well as turnover; here
    retain exposure conservatively because the written exemption names only
    turnover, concentration and the long-run anchors.
    """
    worse, missing = [], []
    for name, key, scale, _width, _precision, good in sw.STANDARD_SET:
        if name == '换手':
            continue
        delta = sw._paired_median(arms, label, key, ref) * good
        if delta != delta:
            missing.append(name)
        elif delta < -(0.005 if scale == 1 else sw.NOISE_BAND):
            worse.append((name, delta, scale))
    ok = not missing and (not worse or (len(worse) == 1 and all(
        delta >= -(0.033 if scale == 1 else sw.RULING_TOLERANCE)
        for _, delta, scale in worse)))
    details = [f'{name} {delta * scale:+.4f}' + ('pp' if scale == 100 else '')
               for name, delta, scale in worse] + [name + '缺' for name in missing]
    return {'第 4 款': (ok, details)}


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def numeric(row):
    return {**{k: sw._field_value(row, k) for k in sw.FIELDS},
            sw.WIN5_KEY: sw.parse_window_series(row[sw.WIN5_KEY])}


def write_csv(name, rows):
    with (EXP / name).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader(); w.writerows(rows)


def main():
    complete = json.loads((EXP / 'completed.json').read_text())
    assert complete['unchanged_frozen_inputs']
    rows = read(EXP / 'summary_rows.csv')
    winners = json.loads((EXP / 'winners.json').read_text())
    groups = {}
    for r in rows:
        arms = groups.setdefault(r['group'], {})
        by_start = arms.setdefault(r['arm'], {})
        assert r['start'] not in by_start
        by_start[r['start']] = numeric(r)
    pairs, decisions, levels, tails = [], {}, {}, []
    for group, arms in groups.items():
        for arm, starts in arms.items():
            assert set(starts) == set(sw.DEFAULT_STARTS)
            data = list(starts.values())
            levels[group + ':' + arm] = {k: st.median(r[k] for r in data)
                for k in sw.FIELDS if k not in sw.DATE_FIELDS}
            worst_dd = max(starts, key=lambda s: starts[s]['最大回撤'])
            worst_ret = min(starts, key=lambda s: starts[s]['滚动5年年化最差'])
            tails.append(dict(group=group, arm=arm,
                min_margin=min(r['最低担保比例'] for r in data),
                min_stock_buffer=min(r['最低股票同跌缓冲'] for r in data),
                min_cash=min(r['最低现金'] for r in data),
                negative_cash_days=sum(r['负现金日数'] for r in data),
                forced_count=sum(r['强平次数'] for r in data),
                forced_paths=sum(r['强平次数'] > 0 for r in data),
                worst_mdd=starts[worst_dd]['最大回撤'], worst_mdd_start=worst_dd,
                worst_5y=starts[worst_ret]['滚动5年年化最差'], worst_5y_start=worst_ret,
                max_single_weight=max(r['单票权重最大'] for r in data)))
            if arm == 'BASE':
                continue
            defects = sw.pairing_defects(arms, arm, 'BASE', sw.DEFAULT_STARTS, group)
            assert not defects, defects
            for start in sw.DEFAULT_STARTS:
                a, b = starts[start], arms['BASE'][start]
                pairs.append(dict(group=group, arm=arm, start=start,
                    P_pp=100 * sw.start_delta(a, b, sw.WIN5_KEY),
                    CAGR_pp=100 * sw.start_delta(a, b, '年化'),
                    P25_pp=100 * sw.start_delta(a, b, '滚动5年年化P25'),
                    DD5_pp=100 * sw.start_delta(a, b, '滚动5年回撤中位'),
                    MDD_pp=100 * sw.start_delta(a, b, '最大回撤'),
                    negative_flip=sw.neg_window_flip(a, b)))
    for arm in ('PV055', 'PV060', 'PV065'):
        verdict, reasons, values = sw.adoption_verdict(groups['full'], groups['A'], arm)
        ug = complete['u_groups'][arm]
        decisions[arm] = dict(verdict=verdict, reasons=reasons, values=values,
            U_group=ug, U_clause4=clause4(groups[ug], arm, 'BASE'),
            U_P_pp=100 * sw._paired_median(groups[ug], arm, sw.WIN5_KEY),
            U_CAGR_pp=100 * sw._paired_median(groups[ug], arm, '年化'))
    # Canonical report supplies decision tables, tails with dates, standard
    # metrics, concentration, both long-run anchors and non-overlapping windows.
    specs = [('A', list(groups['full']), winners['A'])]
    specs += [(complete['u_groups'][a], ['BASE', a], winners['U'][a])
              for a in decisions if complete['u_groups'][a] != 'A']
    for group, labels, excluded in specs:
        lines = [sw.metric_header(), '#MARKET|a', '#EX5|fixed|' + ','.join(excluded)]
        for r in rows:
            if r['group'] not in ('full', group) or r['arm'] not in labels:
                continue
            label = (sw.EX5_PREFIX if r['group'] != 'full' else '') + r['arm']
            lines += ['|'.join([label, r['start']] + [str(sw._field_value(r, k)) for k in sw.FIELDS]),
                      '|'.join(['#WIN5', label, r['start'], r[sw.WIN5_KEY]])]
        path = EXP / f'sweep_full_{group}.txt'
        path.write_text('\n'.join(lines) + '\n')
        with (EXP / f'report_full_{group}.txt').open('w') as f, contextlib.redirect_stdout(f):
            sw.report(path, '低 P/V 取消单票上限；0bp；全部路径共享冻结输入')
    annual, anchors = [], []
    for r in rows:
        if r['start'] not in sw.LONGRUN_STARTS:
            continue
        anchors.append({k: r[k] for k in ('group', 'arm', 'start', '年化', '最大回撤', '互不重叠5年块中位', '末次净值日')})
        nav = read(EXP / 'nav' / (r['tag'] + '.csv'))
        year_ends = {}
        for n in nav:
            year_ends[n['date'][:4]] = n
        for year, end in sorted(year_ends.items()):
            prior = year_ends.get(str(int(year) - 1))
            if prior and end['date'][5:7] == '12':
                annual.append(dict(group=r['group'], arm=r['arm'], start=r['start'],
                    year=year, return_=float(end['net_equity']) / float(prior['net_equity']) - 1))
    for name, data in [('paired_metrics.csv', pairs), ('tails.csv', tails),
                       ('longrun_anchors.csv', anchors), ('annual_returns.csv', annual)]:
        write_csv(name, data)
    result = dict(complete_pairing=True, zero_negative_cash=all(r['负现金日数'] == '0' for r in rows),
        actual_paths=complete['paths'], decisions=decisions, level_medians=levels,
        end_dates=sorted({r['末次净值日'] for r in rows}), production_rule_changed=False)
    (EXP / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(decisions, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
