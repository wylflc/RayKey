"""Paired §12.1 readings for every (candidate, control) pair; Track-A guardrail on NEW vs the same-input control."""
import contextlib
import csv
import json
import os
import statistics as st
import sys

from common import EXP, ROOT, load, save
sys.path.insert(0, str(ROOT / 'scripts'))
import sweep_backtest_configs as sw


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def numeric(r):
    return {**{k: sw._field_value(r, k) for k in sw.FIELDS}, sw.WIN5_KEY: sw.parse_window_series(r[sw.WIN5_KEY])}


def pair_table(rows, cand, ctrl, group):
    sel = [r for r in rows if r['group'] == group]
    arms = {a: {r['start']: numeric(r) for r in sel if r['arm'] == a} for a in (cand, ctrl)}
    defects = sw.pairing_defects(arms, cand, ctrl, sw.DEFAULT_STARTS, group)
    assert not defects, defects
    out = []
    for start in sw.DEFAULT_STARTS:
        n, b = arms[cand][start], arms[ctrl][start]
        tags = [next(r['tag'] for r in sel if r['arm'] == a and r['start'] == start) for a in (ctrl, cand)]
        out.append(dict(candidate=cand, control=ctrl, group=group, start=start,
                        P_pp=100 * sw.start_delta(n, b, sw.WIN5_KEY), CAGR_pp=100 * sw.start_delta(n, b, '年化'),
                        P25_pp=100 * sw.start_delta(n, b, '滚动5年年化P25'), DD5_pp=100 * sw.start_delta(n, b, '滚动5年回撤中位'),
                        MDD_pp=100 * sw.start_delta(n, b, '最大回撤'), negative_flip=sw.neg_window_flip(n, b),
                        min_ratio_delta=n['最低担保比例'] - b['最低担保比例'], forced_delta=n['强平次数'] - b['强平次数'],
                        turnover_delta=n['年均换手'] - b['年均换手'],
                        identical_nav=(EXP / 'nav' / f'{tags[0]}.csv').read_bytes() == (EXP / 'nav' / f'{tags[1]}.csv').read_bytes()))
    return out


def summarize(pairs):
    keys = ('P_pp', 'CAGR_pp', 'P25_pp', 'DD5_pp', 'MDD_pp', 'min_ratio_delta', 'turnover_delta')
    return dict(**{k: st.median(r[k] for r in pairs) for k in keys}, negative_flips=sum(r['negative_flip'] for r in pairs),
                forced_delta=sum(r['forced_delta'] for r in pairs), identical_nav_paths=sum(r['identical_nav'] for r in pairs),
                CAGR_positive=sum(r['CAGR_pp'] > 0 for r in pairs), P_positive=sum(r['P_pp'] > 0 for r in pairs))


def main():
    assert load('completed.json')['unchanged_inputs']
    rows = read(EXP / 'summary_rows.csv')
    winners = load('winners.json')
    arms = sorted({r['arm'] for r in rows})
    control = 'CONTROL' if 'CONTROL' in arms else 'OLD'
    groups = ['full', 'A'] + (['U'] if winners['U'] != winners['A'] else [])
    pairs_spec = [(a, control) for a in arms if a not in ('OLD', 'CONTROL')] + ([('NEW', 'MID')] if {'NEW', 'MID'} <= set(arms) else [])
    if control == 'CONTROL':
        pairs_spec.append(('CONTROL', 'OLD'))
    all_pairs, checks = [], []
    for cand, ctrl in pairs_spec:
        for group in groups:
            p = pair_table(rows, cand, ctrl, group)
            all_pairs += p
            c = dict(candidate=cand, control=ctrl, group=group, **summarize(p))
            if group == 'full':
                c['track_a_pass'] = (c['P_pp'] >= -1 and c['CAGR_pp'] >= -1 and c['DD5_pp'] <= 3
                                     and c['negative_flips'] <= len(sw.DEFAULT_STARTS) / 2)
            checks.append(c)
    # §12.1 第 2 款双表判定（全样本 + 去赢家 A）：sw.report 以名为 BASE 的臂为对照
    for cand in [a for a in arms if a.startswith('NEW') or a == 'MID']:
        for group in groups[1:]:
            text = []
            for g in ('full', group):
                for line in (EXP / f'sweep_{g}.txt').read_text().splitlines()[(0 if g == 'full' else 2):]:
                    label = line.split('|', 1)[0].replace('#WIN5', '').replace('EX5:', '')
                    keep = line.startswith(('#METRIC', '#MARKET', '#EX5')) or any(
                        line.startswith(p) for p in (f'{cand}|', f'EX5:{cand}|', f'#WIN5|{cand}|', f'#WIN5|EX5:{cand}|',
                                                     f'{control}|', f'EX5:{control}|', f'#WIN5|{control}|', f'#WIN5|EX5:{control}|'))
                    if keep:
                        for src in (control,):
                            for a, b in ((f'{src}|', 'BASE|'), (f'#WIN5|{src}|', '#WIN5|BASE|'), (f'EX5:{src}|', 'EX5:BASE|'),
                                         (f'#WIN5|EX5:{src}|', '#WIN5|EX5:BASE|')):
                                if line.startswith(a):
                                    line = b + line[len(a):]
                        text.append(line)
            combined = EXP / f'sweep_{cand}_full_{group}.txt'
            combined.write_text('\n'.join(text) + '\n')
            with (EXP / f'report_{cand}_full_{group}.txt').open('w') as f, contextlib.redirect_stdout(f):
                sw.report(combined, f'OI-200～203：{cand} vs {control}（同冻结输入、同 BASE、0bp）')
    for name, data in (('paired_metrics.csv', all_pairs), ('guardrails.csv', checks)):
        fields = list(dict.fromkeys(k for r in data for k in r))
        with (EXP / name).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(data)
    levels = {}
    for group in groups:
        for arm in arms:
            sel = [numeric(r) for r in rows if r['group'] == group and r['arm'] == arm]
            levels[f'{group}:{arm}'] = {k: st.median(r[k] for r in sel) for k in
                                        ('年化', '最大回撤', '滚动5年年化中位', '滚动5年年化P25', '滚动5年回撤中位', '年均换手')}
    main_check = next(c for c in checks if c['candidate'] == 'NEW' and c['control'] == control and c['group'] == 'full')
    save('verification.json', dict(control=control, guardrails=checks, track_a_pass=main_check['track_a_pass'],
                                   zero_negative_cash=all(r['负现金日数'] == '0' for r in rows), winners=winners,
                                   level_medians=levels, job_id=os.getenv('SLURM_JOB_ID')))
    print(json.dumps(dict(guardrails=checks, levels=levels), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
