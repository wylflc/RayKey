"""Render the stop-rule comparison from verified paired summaries."""
import csv
import json
from run import EXP, ROOT


def read(name):
    with (EXP / name).open() as f:
        return list(csv.DictReader(f))


def main():
    v = json.loads((EXP / 'verification.json').read_text())
    idx = {(r['group'], r['arm'], r['metric']): r for r in read('paired_metrics.csv')}
    anchors = read('anchors.csv')
    winners = json.loads((EXP / 'winner_sets.json').read_text())
    m = json.loads((EXP / 'manifest.json').read_text())
    def level(group, arm, key, scale=100):
        return float(idx[group, arm, key]['level_median']) * scale
    def delta(group, key, scale=100):
        return float(idx[group, 'STOPMAX', key]['paired_delta_median']) * scale
    def table(group):
        lines = ['| 指标（14起点中位数） | 原规则 min | 新规则 max | 同起点配对差中位 |',
                 '| --- | ---: | ---: | ---: |']
        for key, scale, unit in [('年化',100,'%'),('最大回撤',100,'%'),('滚动5年年化P25',100,'%'),
                ('滚动5年回撤中位',100,'%'),('互不重叠5年块中位',100,'%'),('逐年收益中位',100,'%'),
                ('平均仓位',100,'%'),('年均换手',1,'倍')]:
            dunit = 'pp' if scale == 100 else '倍'
            lines.append(f'| {key} | {level(group,"BASE",key,scale):.2f}{unit} | '
                         f'{level(group,"STOPMAX",key,scale):.2f}{unit} | {delta(group,key,scale):+.2f}{dunit} |')
        return '\n'.join(lines)
    main_delta = delta('full', '年化')
    better = idx['full', 'STOPMAX', '年化']['positive_starts']
    lines = ['# MA60止损改取最大值的收益对照（2026-09-16）', '',
        f'取最大值后，全期年化的同起点配对差中位为 **{main_delta:+.2f}个百分点**，'
        f'14个标准起点中有 **{better}个**提高。按现行回测判据：**{v["verdict"]}**。生产规则保持原样。', '',
        '止损线由 `min(建仓日MA60锚, 当日MA60)` 改成 `max(建仓日MA60锚, 当日MA60)`；'
        '只改这一项。锚随公司行动调整，加仓不重设；当日均线可以回落，未使用持有期间均线最高值。', '',
        '## 全样本', '', table('full'), '',
        '表中配对差先按同一起点相减再取中位，不等于两个水平中位数相减。回撤以正数列示，越小越好。', '',
        '## 剔除赢家对照与同窗读数', '',
        '| 样本 | 滚5同窗年化配对差 | 全期年化：原规则 | 全期年化：新规则 | 年化配对差 | 最大回撤配对差 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |']
    for group, label in [('full','全样本'),('A','剔除BASE前五赢家 A'),('U','剔除两臂赢家并集 U')]:
        lines.append(f'| {label} | {delta(group,"滚动5年窗口年化"):+.2f}pp | '
                     f'{level(group,"BASE","年化"):.2f}% | {level(group,"STOPMAX","年化"):.2f}% | '
                     f'{delta(group,"年化"):+.2f}pp | {delta(group,"最大回撤"):+.2f}pp |')
    lines += ['', f'A：`{",".join(winners["A"])}`；U：`{",".join(winners["U"])}`。'
              + ('U=A，复用同一对照。' if winners['U_reused_A'] else 'U单独重跑两臂。'),
        f'去赢家全面优秀：{"是" if v["U_excellent"] else "否"}。判定依据：' + '；'.join(v['reasons']) + '。', '',
        '## 300万元空仓启动的两条长跑路径', '',
        '| 起点 | 规则 | 期末净资产（万元） | 累计收益 | 年化 | 最大回撤 | 买入/卖出笔数 | 平均持有天数 |',
        '| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for start in ('2009-11-01','2011-11-01'):
        for arm, label in [('BASE','原规则 min'),('STOPMAX','新规则 max')]:
            r = next(r for r in anchors if r['group']=='full' and r['start']==start and r['arm']==arm)
            lines.append(f'| {start} | {label} | {float(r["final_equity"])/10000:,.2f} | '
                f'{float(r["total_return_pct"]):,.2f}% | {float(r["cagr_pct"]):.2f}% | '
                f'{float(r["mdd_pct"]):.2f}% | {r["buys"]}/{r["sells"]} | {float(r["average_holding_days"]):.1f} |')
    lines += ['', '净资产含现金与剩余持仓市值、扣除融资负债，计入手续费、税费和融资利息；'
        '期末未假设清仓，不额外扣期末退出费用。滑点沿用默认0bp。', '',
        '## 数据与验证', '',
        '- 当前正式BASE、历史v6b面板、14个标准起点（2009-11至2016-05），m3/月末锚定5年同窗。'
        '本金300万元，所有融资、股债仓位限制、换仓与加减仓规则保持相同。',
        '- 历史价格末日：' + '、'.join(f'{n}只截至{d}' for d,n in sorted(m['price_end_counts'].items()))
        + '。本批净值末日为2026-08-28；部分股票缺少8月7日后的历史报价，'
        '沿用引擎停牌/缺价处理。两臂输入相同，不代表截至9月16日的市场表现。',
        '- 加速用状态子集与生产文件的哈希均保持既有逐行等价验证的版本，正式面板哈希一致；'
        '跑前、跑后全部输入指纹一致。',
        f'- 共{v["paths"]}条正式路径，起点和窗口完整配对，负现金日数为0。'
        f'与前次已登记现行BASE的28条路径相比，指标/窗口字段差异为{v["baseline_reference_differences"]}项。',
        '- 26项止损、执行时点、参数同步及剔除集检查通过；小样本作业26793428，正式作业26793527。'
        '完整资源记录见实验目录。',
        '- 本轮只有1个候选，未选择参数最优点。多起点共享终点、滚动窗口重叠，历史频率不等于独立样本概率；'
        '参数与股票池仍有历史研究选择影响，绝对收益不作未来预期。', '',
        '## 可复现证据', '',
        '- [标准全样本/A报告](../../data/experiments/exp_stop_max_20260916/report_full_A.txt)：'
        '决策、尾部、标准指标、集中度及两个长跑锚点。',
        '- [赢家并集U报告](../../data/experiments/exp_stop_max_20260916/report_U.txt)：'
        '同一剔除集下的收益、回撤、负收益窗口、集中度与尾部。',
        '- [完整逐路径摘要](../../data/experiments/exp_stop_max_20260916/summary_rows.csv)、'
        '[配对指标](../../data/experiments/exp_stop_max_20260916/paired_metrics.csv)、'
        '[核验结果](../../data/experiments/exp_stop_max_20260916/verification.json)。',
        '- [预登记与口径](../../data/experiments/exp_stop_max_20260916/preregister.md)、'
        '[输入指纹](../../data/experiments/exp_stop_max_20260916/manifest.json)。', '',
        '复现先提交 `STAGE=smoke` 作业核验输入与资源，再提交 `STAGE=scan`：', '',
        '```bash',
        'sbatch --account=tes21035 --cpus-per-task=16 --export=ALL,STAGE=smoke scripts/slurm/stop_max_20260916.sbatch',
        'sbatch --account=tes21035 --export=ALL,STAGE=scan scripts/slurm/stop_max_20260916.sbatch',
        'python3 data/experiments/exp_stop_max_20260916/analyze.py',
        'python3 data/experiments/exp_stop_max_20260916/render.py',
        '```', '']
    (ROOT / 'docs/reports/stop_max_backtest_2026-09-16.zh.md').write_text('\n'.join(lines))


if __name__ == '__main__':
    main()
