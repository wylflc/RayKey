#!/usr/bin/env python3
"""Render the completed, independently rerun startup return experiment."""
import argparse
import csv
import json
from pathlib import Path


def read_csv(path):
    with path.open(encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def pct(x):
    return f'{float(x):+.2%}' if x != '' else '—'


def table(headers, rows):
    return '\n'.join(['| ' + ' | '.join(headers) + ' |',
                      '| ' + ' | '.join(['---'] * len(headers)) + ' |',
                      *['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--exp', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    args = ap.parse_args()
    exp = args.exp
    manifest = json.loads((exp / 'manifest.json').read_text())
    complete = json.loads((exp / 'completed.json').read_text())
    if not complete['unchanged_inputs']:
        raise ValueError('Input verification did not pass')
    # Keep compact delivered CSVs in repository LF form; numeric cells are unchanged.
    for path in exp.glob('*.csv'):
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f))
        with path.open('w', encoding='utf-8-sig', newline='') as f:
            csv.writer(f, lineterminator='\n').writerows(rows)
    coverage = json.loads((exp / 'coverage.json').read_text())
    stats = read_csv(exp / 'horizon_summary.csv')
    primary = [r for r in stats if r['group'] == 'all_available']
    common = [r for r in stats if r['group'] == 'same_starts_with_36m']
    blocks = read_csv(exp / 'nonoverlapping_summary.csv')
    starts = read_csv(exp / 'returns_by_start.csv')
    labels = {'1': '1 个月', '3': '3 个月', '6': '半年', '12': '1 年', '36': '3 年'}
    root = Path(__file__).resolve().parents[2]
    exp_rel = exp.resolve().relative_to(root)
    link = '../../' + str(exp_rel)
    lines = [
        '# 不同起点启动策略后的收益统计（2026-09-15）', '',
        f'按当前 {manifest["workflow"]} 策略，从 2009 年 11 月至 2026 年 8 月的 '
        f'{complete["paths"]} 个每月起点分别空仓启动。下表均为**累计净资产收益率，未经年化**。', '',
        '## 1. 所有完整起点的收益分布', '',
        table(['执行期限', '完整起点数', '平均收益', '收益中位数', '盈利起点占比', 'P10', '最差收益', '最好收益'],
              [[labels[r['months']], r['count'], pct(r['mean']), pct(r['median']),
                f'{float(r["positive_share"]):.1%} ({r["positive_count"]}/{r["count"]})',
                pct(r['p10']), pct(r['worst']), pct(r['best'])] for r in primary]), '',
        'P10 表示约 10% 的历史起点收益低于该水平；盈利按收益严格大于 0 统计。'
        '均值按每个启动月份等权计算；长期均值可能受到少数高收益起点影响，应结合中位数阅读。', '',
        f'前 1 个月有 {primary[0]["zero_count"]} 个起点收益为零（本轮均为尚未建仓）；'
        f'前 3 个月有 {primary[1]["zero_count"]} 个零收益起点。因此盈利比例的补数同时包含亏损和零收益。', '',
        table(['期限', '最差启动月', '对应收益', '最好启动月', '对应收益', '期限不足的起点数'],
              [[labels[r['months']], r['worst_start'][:7], pct(r['worst']),
                r['best_start'][:7], pct(r['best']),
                coverage[r['months']].get('insufficient_followup', 0)] for r in primary]), '',
        '## 2. 每年年初启动的示例', '',
        '下表选取每年 1 月，以及全样本最早的 2009 年 11 月。完整逐月明细见'
        f' [returns_by_start.csv]({link}/returns_by_start.csv)，'
        f'实际起止日、期末净资产与期间回撤见 [returns_long.csv]({link}/returns_long.csv)。', '',
        table(['启动月份', '前 1 个月', '前 3 个月', '前半年', '前 1 年', '前 3 年'],
              [[r['start'][:7], *[pct(r[f'return_{m}m']) for m in (1, 3, 6, 12, 36)]]
               for r in starts if r['start'][5:7] == '01' or r['start'] == manifest['first']]), '',
        '“—”表示历史数据不足以覆盖完整期限；不代表零收益。CSV 中收益以小数存储（例如 0.10 = 10%）。', '',
        '## 3. 相同启动月份的期限对照', '',
        '只保留有完整三年历史的启动月份，让五个期限使用完全相同的起点集合。'
        '这张表可减少期限间样本年份不同造成的混淆。', '',
        table(['执行期限', '共同起点数', '平均收益', '收益中位数', '盈利起点占比', 'P10'],
              [[labels[r['months']], r['count'], pct(r['mean']), pct(r['median']),
                f'{float(r["positive_share"]):.1%}', pct(r['p10'])] for r in common]), '',
        '## 4. 互不重叠时间段的检查', '',
        '固定从 2009 年 11 月开始，以各期限等距抽取起点。每个期限内部的观测区间互不重叠；'
        '这只是另一种历史描述，起点未按收益挑选。', '',
        table(['执行期限', '区间数', '平均收益', '收益中位数', '盈利区间占比', '最差收益'],
              [[labels[r['months']], r['count'], pct(r['mean']), pct(r['median']),
                f'{float(r["positive_share"]):.1%}', pct(r['worst'])] for r in blocks]), '',
        '## 5. 回测口径与验证', '',
        '- 策略参数直接读取 `sweep_backtest_configs.BASE`，初始本金 300 万元；每个起点独立清零持仓、'
        '负债与交易冷却。历史均线、估值、股票池与股债约束状态仍使用启动时已经可得的历史。',
        '- 每月首个交易日收盘开始生成信号，最快下一交易日收盘首次成交；未出现合格信号时继续持有现金。',
        '- 按自然月份计期：例如 2010-01 启动，前 3 个月取 2010-03 最后交易日。'
        '收益 = 期末净资产 ÷ 初始本金 − 1，保留首日等待和建仓期。',
        '- 净资产包含现金和股票市值并扣除融资负债；计入实际路径的手续费、税费、分红及融资利息，'
        '滑点 0bp。期末为继续持仓的盯市结果，未扣假设全仓卖出的退出费用。',
        '- 历史行情缓存中，155 股止于 2026-08-07，140 股止于 08-28，另 1 股已退市。'
        '本轮统一截至 2026-08-07，完整月份只到 2026-07；不把缺失后段用旧价格填满。'
        '本报告不是截至 9 月 15 日的行情更新回测。',
        '- 采用历史时点股票池及正式生产估值；本轮复核生产全文件和加速用子集的文件摘要，'
        '均与已完成逐行等价审计的输入一致。',
        f'- 已登记 2011-11 长跑基准的 {complete["baseline_fields"]} 个指标/窗口字段完全复现；'
        f'该起点独立三年路径的 {complete["prefix_rows_verified"]} 个逐日记录与长跑前缀完全一致。',
        '- 所有完整窗口均校验交易日日历覆盖、现金起始状态、净资产有限值；全部路径负现金日数为 0。'
        '跑前、跑后输入哈希一致。日期边界等 7 项单元测试及 4 项参数同步测试通过。',
        f'- SLURM 作业：`{complete["job_id"]}`。配置和输入指纹见 '
        f'[预登记]({link}/preregister.md)、[manifest.json]({link}/manifest.json)、'
        f'[完成核验]({link}/completed.json)。', '',
        '## 6. 解释边界', '',
        '主表的月度起点大量重叠，盈利比例是这些历史起点的频率，不能视作相互独立的成功概率。'
        '不同期限的完整起点集合不同，应同时查看第 3 节。当前参数经过历史回测选择，'
        '本次是固定现行策略的历史复算，不是事前冻结参数的样本外业绩，也不能据此推算未来收益。', '',
        '复现：', '',
        '```bash',
        'sbatch --account=tes21035 scripts/slurm/startup_horizon_returns_20260915.sbatch',
        'python3 scripts/experimental/render_startup_returns.py \\',
        f'  --exp {exp_rel} \\',
        f'  --report {args.report}',
        '```', '',
    ]
    args.report.write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
