"""Audit successful repeated triggers and summarize their effect on transactions."""
import csv
import json
import math
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path
from run import EXP, sw, save
from analyze import write


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def main():
    winners = json.loads((EXP / 'winner_sets.json').read_text())
    results, examples = [], []
    for group in ('full', 'A', 'U'):
        suffix = 'full_A' if group != 'U' or winners['U_reused_A'] else ''
        for arm in ('BASE', 'REPEAT'):
            for start in sw.DEFAULT_STARTS:
                tag = sw.summary_tag(arm, start, '' if group == 'full' else 'excluded')
                events = read(EXP / 'swaps' / suffix / f'{tag}.csv')
                sources = Counter((r['exec_date'], r['source']) for r in events)
                assert max(sources.values(), default=0) <= 1, (group, arm, start, 'source repeated')
                pairs = defaultdict(list)
                for r in events:
                    assert float(r['shares']) > 0
                    assert float(r['funds_before']) < float(r['buy_tranche']) + 1e-8
                    if r['gain_source'] == 'False':
                        assert float(r['source_pv']) - float(r['candidate_pv']) >= .15 - 1e-8
                    pairs[r['exec_date'],r['target']].append(r)
                extras = [r for rows in pairs.values() for r in rows[1:]]
                if arm == 'BASE': assert not extras
                gross = sum(float(r['shares'])*float(r['price']) for r in events)
                extra_gross = sum(float(r['shares'])*float(r['price']) for r in extras)
                tiny_gap = [r for r in extras if 0 <= float(r['funds_before']) and
                            float(r['buy_tranche'])-float(r['funds_before']) <= .01*float(r['buy_tranche'])]
                results.append(dict(group=group, arm=arm, start=start,
                    swap_sales=len(events), distinct_targets=len(pairs),
                    repeated_target_days=len({d for (d,c), rows in pairs.items() if len(rows)>1}),
                    multi_source_targets=sum(len(rows)>1 for rows in pairs.values()),
                    extra_source_sales=len(extras), maximum_sources_per_target=max(map(len,pairs.values()),default=0),
                    gross_swap_sales=gross, extra_gross_swap_sales=extra_gross,
                    extra_sales_for_gap_within_one_percent_of_tranche=len(tiny_gap)))
                if group == 'full' and arm == 'REPEAT' and start == sw.EX5_ANCHOR_START:
                    for (day, target), rows in pairs.items():
                        if len(rows)>1:
                            for i,r in enumerate(rows,1): examples.append(dict(sequence=i, **r))
    write('mechanism_paths.csv', results)
    if examples: write('repeated_trigger_examples.csv', examples)
    summary = []
    for group in ('full','A','U'):
        for arm in ('BASE','REPEAT'):
            rows = [r for r in results if r['group']==group and r['arm']==arm]
            extras = sum(r['extra_source_sales'] for r in rows)
            summary.append(dict(group=group,arm=arm,paths=len(rows),
                median_swap_sales=st.median(r['swap_sales'] for r in rows),
                median_repeated_target_days=st.median(r['repeated_target_days'] for r in rows),
                extra_source_sales_sum=extras,
                extra_sales_tiny_gap_fraction=(sum(r['extra_sales_for_gap_within_one_percent_of_tranche'] for r in rows)/extras if extras else 0),
                maximum_sources_per_target=max(r['maximum_sources_per_target'] for r in rows)))
    save('mechanism_verification.json',dict(source_once_per_day=True,margin_and_funding_conditions_preserved=True,
        zero_quantity_sales=False, baseline_repeated_triggers=0,groups=summary,
        repeated_observations_note='不同起点共享历史，合计事件数仅为路径内审计计数，不是独立市场样本数。'))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
