"""Pair OLD/NEW per start and report the §12.1 Track A guardrail (OI-197, cash/price basis repair)."""
import contextlib
import csv
import json
import statistics as st
import sys
from pathlib import Path
EXP = Path(__file__).resolve().parent
ROOT = EXP.parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def numeric(r):
    return {**{k: sw._field_value(r, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(r[sw.WIN5_KEY])}


def main():
    complete = json.loads((EXP / 'completed.json').read_text()); assert complete['unchanged_inputs']
    rows = read(EXP / 'summary_rows.csv')
    winners = json.loads((EXP / 'winners.json').read_text())
    groups = ['full', 'A'] + (['U'] if winners['U'] != winners['A'] else [])
    pairs, checks = [], []
    for group in groups:
        selected = [r for r in rows if r['group'] == group]
        arms = {a: {r['start']: numeric(r) for r in selected if r['arm'] == a} for a in ('OLD', 'NEW')}
        defects = sw.pairing_defects(arms, 'NEW', 'OLD', sw.DEFAULT_STARTS, group)
        assert not defects, defects
        nav_equal = 0
        for start in sw.DEFAULT_STARTS:
            n, b = arms['NEW'][start], arms['OLD'][start]
            pairs.append(dict(group=group, start=start,
                              P_pp=100 * sw.start_delta(n, b, sw.WIN5_KEY), CAGR_pp=100 * sw.start_delta(n, b, '年化'),
                              P25_pp=100 * sw.start_delta(n, b, '滚动5年年化P25'), DD5_pp=100 * sw.start_delta(n, b, '滚动5年回撤中位'),
                              MDD_pp=100 * sw.start_delta(n, b, '最大回撤'), negative_flip=sw.neg_window_flip(n, b),
                              min_ratio_delta=n['最低担保比例'] - b['最低担保比例'], forced_delta=n['强平次数'] - b['强平次数'],
                              turnover_delta=n['年均换手'] - b['年均换手']))
            pair = [next(r for r in selected if r['arm'] == a and r['start'] == start) for a in ('OLD', 'NEW')]
            nav_equal += int((EXP / 'nav' / f"{pair[0]['tag']}.csv").read_bytes() == (EXP / 'nav' / f"{pair[1]['tag']}.csv").read_bytes())
        current = [r for r in pairs if r['group'] == group]
        check = dict(group=group, **{k: st.median(r[k] for r in current) for k in ('P_pp', 'CAGR_pp', 'P25_pp', 'DD5_pp', 'MDD_pp', 'min_ratio_delta', 'turnover_delta')},
                     negative_flips=sum(r['negative_flip'] for r in current), forced_delta=sum(r['forced_delta'] for r in current),
                     identical_nav_paths=nav_equal, cagr_positive=sum(r['CAGR_pp'] > 0 for r in current), P_positive=sum(r['P_pp'] > 0 for r in current))
        if group == 'full':
            check['track_a_pass'] = check['P_pp'] >= -1 and check['CAGR_pp'] >= -1 and check['DD5_pp'] <= 3 and check['negative_flips'] <= len(sw.DEFAULT_STARTS) / 2
        checks.append(check)
    for group in groups[1:]:
        combined = EXP / f'sweep_full_{group}.txt'
        text = (EXP / 'sweep_full.txt').read_text() + '\n'.join((EXP / f'sweep_{group}.txt').read_text().splitlines()[2:]) + '\n'
        # sw.report pairs against the arm literally named BASE: OLD (registered inputs) is that control
        for src, dst in (('OLD|', 'BASE|'), ('#WIN5|OLD|', '#WIN5|BASE|'), ('EX5:OLD|', 'EX5:BASE|'), ('#WIN5|EX5:OLD|', '#WIN5|EX5:BASE|')):
            text = '\n'.join((dst + line[len(src):]) if line.startswith(src) else line for line in text.split('\n'))
        combined.write_text(text)
        with (EXP / f'report_full_{group}.txt').open('w') as f, contextlib.redirect_stdout(f):
            sw.report(combined, 'OI-197 实付股息与交易所价格参数分流：NEW（修复后）vs OLD（718783ce），同 BASE，0bp（轨道 A 见 verification.json）')
    for name, data in (('paired_metrics.csv', pairs), ('guardrails.csv', checks)):
        fields = list(dict.fromkeys(k for r in data for k in r))
        with (EXP / name).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(data)
    levels = {}
    for group in groups:
        for arm in ('OLD', 'NEW'):
            sel = [numeric(r) for r in rows if r['group'] == group and r['arm'] == arm]
            levels[f'{group}:{arm}'] = {k: st.median(r[k] for r in sel) for k in ('年化', '最大回撤', '滚动5年年化中位', '滚动5年年化P25', '滚动5年回撤中位', '年均换手')}
    verification = dict(complete_pairing=True, zero_negative_cash=all(r['负现金日数'] == '0' for r in rows), guardrails=checks,
                        track_a_pass=next(c for c in checks if c['group'] == 'full')['track_a_pass'],
                        winners_unchanged=winners['by_arm']['OLD'] == winners['by_arm']['NEW'], U_reused=winners['A'] == winners['U'],
                        actual_paths=complete['paths'], level_medians=levels)
    (EXP / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(guardrails=checks, levels=levels), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
