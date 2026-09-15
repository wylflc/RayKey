#!/usr/bin/env python3
"""Summarize calendar-quarter starts from verified independent monthly paths."""
import argparse
import collections
import csv
import json
import math
import statistics
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from render_startup_returns import pct, read_csv, table
from startup_horizon_returns import HORIZONS, ROOT, aggregate, digest, period_end


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=ROOT / 'data/experiments/exp_startup_returns_20260915')
    ap.add_argument('--report', type=Path, default=ROOT / 'docs/reports/startup_returns_quarterly_2026-09-15.zh.md')
    args = ap.parse_args()
    source = args.source.resolve()
    out = source / 'quarterly'
    out.mkdir(exist_ok=True)
    meta = json.loads((source / 'manifest.json').read_text())
    completed = json.loads((source / 'completed.json').read_text())
    if not completed['unchanged_inputs']:
        raise ValueError('Source run has not passed input verification')
    source_names = ('manifest.json', 'completed.json', 'independent_verification.json',
                    'returns_long.csv', 'returns_by_start.csv', 'path_summaries.csv')
    paths = [source / p for p in source_names]
    paths += [Path(__file__).resolve(), Path(__file__).with_name('startup_horizon_returns.py'),
              Path(__file__).with_name('render_startup_returns.py')]
    inputs = {str(p.relative_to(ROOT)): digest(p) for p in paths}
    # Calendar quarters, not three-month intervals anchored on November 2009.
    expected = [date(y, m, 1).isoformat()
                for y in range(int(meta['first'][:4]), int(meta['cutoff'][:4]) + 1)
                for m in (1, 4, 7, 10)
                if meta['first'] <= date(y, m, 1).isoformat() <= meta['cutoff']]
    starts = [s for s in meta['starts'] if s[5:7] in ('01', '04', '07', '10')]
    if starts != expected:
        raise ValueError('Source monthly paths do not cover every calendar-quarter start')
    selected = set(starts)
    raw = [r for r in read_csv(source / 'returns_long.csv') if r['start'] in selected]
    wide = [r for r in read_csv(source / 'returns_by_start.csv') if r['start'] in selected]
    summaries = [r for r in read_csv(source / 'path_summaries.csv') if r['start'] in selected]
    assert len(raw) == len(starts) * len(HORIZONS)
    assert len(wide) == len(summaries) == len(starts)
    assert all(r['负现金日数'] == '0' for r in summaries)
    assert len({(r['start'], r['months']) for r in raw}) == len(raw)
    wide_by_start = {r['start']: r for r in wide}
    rows = []
    for r in raw:
        m = int(r['months'])
        assert r['scheduled_end'] == period_end(r['start'], m)
        complete = r['scheduled_end'] <= meta['cutoff']
        assert (r['status'] == 'complete') == complete
        assert wide_by_start[r['start']][f'return_{m}m'] == r['cumulative_return']
        if complete:
            assert math.isclose(float(r['end_equity']) / meta['capital'] - 1,
                                float(r['cumulative_return']), abs_tol=1e-12)
        else:
            assert r['cumulative_return'] == ''
        rows.append({**r, 'months': m,
                     'cumulative_return': float(r['cumulative_return']) if complete else ''})
    stats = aggregate(rows, 'all_available')
    common = {r['start'] for r in rows if r['months'] == 36 and r['status'] == 'complete'}
    stats += aggregate([r for r in rows if r['start'] in common], 'same_starts_with_36m')
    first = date.fromisoformat(starts[0])
    blocks = [r for r in rows if r['status'] == 'complete' and
              ((int(r['start'][:4]) - first.year) * 12 + int(r['start'][5:7]) - first.month)
              % r['months'] == 0]
    block_stats = aggregate(blocks, 'nonoverlapping')
    for m in HORIZONS:
        own = sorted([r for r in blocks if r['months'] == m], key=lambda r: r['start'])
        assert all(a['end_date'] < b['start'] for a, b in zip(own, own[1:]))
        vals = [r['cumulative_return'] for r in rows if r['months'] == m and r['status'] == 'complete']
        s = next(s for s in stats if s['months'] == m and s['group'] == 'all_available')
        assert s['count'] == len(vals)
        assert math.isclose(s['mean'], sum(vals) / len(vals), abs_tol=1e-12)
        assert math.isclose(s['median'], statistics.median(vals), abs_tol=1e-12)
    coverage = {str(m): dict(collections.Counter(r['status'] for r in rows if r['months'] == m))
                for m in HORIZONS}
    for name, content in [('returns_long.csv', raw), ('returns_by_start.csv', wide),
                          ('path_summaries.csv', summaries), ('horizon_summary.csv', stats),
                          ('nonoverlapping_windows.csv', blocks), ('nonoverlapping_summary.csv', block_stats)]:
        write_csv(out / name, content)
    manifest = dict(created_beijing=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                    selection='calendar quarter starts: January, April, July, October',
                    source_run=str(source.relative_to(ROOT)), source_job_id=completed['job_id'],
                    workflow=meta['workflow'], capital=meta['capital'], cutoff=meta['cutoff'],
                    starts=starts, inputs=inputs, coverage=coverage,
                    reused_independent_paths=len(starts),
                    verified_complete_returns=sum(r['status'] == 'complete' for r in rows),
                    no_new_backtest=True)
    labels = {1: '1 个月', 3: '3 个月', 6: '半年', 12: '1 年', 36: '3 年'}
    link = '../../' + str(out.relative_to(ROOT))
    def main_table(data):
        return table(['执行期限', '完整起点数', '平均收益', '收益中位数', '盈利比例', '最差收益', '最好收益'],
                     [[labels[r['months']], r['count'], pct(r['mean']), pct(r['median']),
                       f'{r["positive_share"]:.1%} ({r["positive_count"]}/{r["count"]})',
                       pct(r['worst']), pct(r['best'])] for r in data])
    lines = ['# 每季度启动策略后的收益统计（2026-09-15）', '',
             f'按用户指定的自然季度频率，取 2010 年第一季度至 2026 年第三季度共 {len(starts)} 个独立起点。'
             '各季度首个交易日收盘形成信号，最快下一交易日收盘成交。每次从 300 万元现金、零持仓与零负债开始。', '',
             '**以下为累计净资产收益率，未经年化。** 策略沿用 v4.188 BASE，含融资及交易费税，滑点 0bp。'
             '行情统一截至 2026-08-07，完整月份到 2026-07；未满期留空。', '',
             '## 1. 季度起点汇总', '', main_table(stats[:5]), '',
             table(['期限', '最差启动季度', '最好启动季度', '未满期起点数'],
                   [[labels[r['months']], r['worst_start'][:7], r['best_start'][:7],
                     coverage[str(r['months'])].get('insufficient_followup', 0)] for r in stats[:5]]), '',
             '## 2. 全部季度起点明细', '',
             f'[逐季度 CSV]({link}/returns_by_start.csv)；'
             f'[实际日期、期末净资产和期间回撤]({link}/returns_long.csv)。CSV 收益为小数，0.10 表示 10%。', '',
             table(['启动季度', '首次信号日', '前 1 个月', '前 3 个月', '前半年', '前 1 年', '前 3 年'],
                   [[f'{r["start"][:4]} Q{(int(r["start"][5:7]) - 1) // 3 + 1}', r['first_signal_date'],
                     *[pct(r[f'return_{m}m']) for m in HORIZONS]] for r in wide]), '',
             '“—”表示不足完整期限，不是零收益。', '',
             '## 3. 同一组起点的期限对照', '',
             '五个期限均限制在有完整三年数据的季度起点上，减少样本年份差异。', '', main_table(stats[5:]), '',
             '## 4. 时间段互不重叠的检查', '',
             '固定从 2010 年第一季度开始，在季度起点中按期限筛选互不重叠区间；不根据收益选择起点。', '',
             main_table(block_stats), '',
             '## 5. 来源、验证与解释', '',
             '- 季度起点为每年 1／4／7／10 月首个交易日。月度来源始于 2009-11，'
             '不覆盖 2009 年第四季度的季度初，因此首个完整季度起点为 2010-01。',
             '- 直接筛选上一轮已分别空仓启动的独立路径；本次没有重新运行交易引擎。'
             '每条路径及每个期限的数值均与来源逐项一致。',
             f'- 来源 SLURM 作业 {completed["job_id"]} 已完成 48 个基准字段复现、727 条短长路径前缀检查及 '
             '952 个完整期限收益的独立复算。本次核对季度覆盖、316 个完整期限的本金分母与明细一致性、'
             '未满期空值、非重叠区间和汇总统计；67 条来源路径负现金日数全部为 0。',
             '- 收益 = 期末净资产 ÷ 初始本金 − 1，按自然月份取最后交易日，期末继续持仓，'
             '未扣假设全仓清算费用。起点以前的均线、估值、时点股票池和股债状态历史保留。',
             '- 季度起点下，半年、一年和三年窗口仍有重叠；盈利比例仅为历史频率，不能视作独立成功概率。'
             '现行参数经过历史选择，这些结果不代表未来收益或事前冻结参数的样本外业绩。',
             f'- 来源文件哈希与本次覆盖核验见 [manifest.json]({link}/manifest.json)；'
             '原月度报告和实验输出保留供追溯。', '',
             '复现：`python3 scripts/experimental/summarize_startup_quarters.py`。', '']
    args.report.write_text('\n'.join(lines))
    assert all(digest(ROOT / p) == meta for p, meta in inputs.items())
    manifest['source_files_unchanged'] = True
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(main_table(stats[:5]))
    print('Quarterly paths:', len(starts), 'complete returns:', manifest['verified_complete_returns'])


if __name__ == '__main__':
    main()
