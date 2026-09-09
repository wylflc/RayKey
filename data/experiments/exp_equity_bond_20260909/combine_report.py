"""Produce one user-facing report for both preregistered policy branches."""
import csv
import json
from pathlib import Path
EXP=Path(__file__).resolve().parent
ROOT=EXP.parents[2]


def main():
    cases={}
    for stage,path in (('cap',EXP),('low_only',EXP/'high_base')):
        rows=list(csv.DictReader((path/'results.csv').open()))
        for r in rows:cases[stage,r['arm']]=r
    first=json.loads((EXP/'verification.json').read_text())
    second=json.loads((EXP/'high_base/verification.json').read_text())
    qa=json.loads((EXP/'qa.json').read_text());qb=json.loads((EXP/'high_base/qa.json').read_text())
    text=['# 股债性价比约束实验','',
      '暂不采纳生产。分位去融资和0～160%映射均未发现稳健改善；绝对利差3pp有历史线索，但滚动5年指标未过线、相邻阈值不支持，且必须先处理BASE记账缺陷。', '',
      '将股债性价比接入回测：用沪深300整体滚动盈利收益率减中国10年国债收益率，按月更新、T+1执行。性价比越低，限制越严格。历史分位只使用当时观测日前最多60个月。',
      '共17个信号候选、2个固定仓位控制；两轮均有BASE，14个起点、全样本/A/每臂赢家并集U。现有生产参数保持。',
      '', '## 中心方案与控制', '',
      '以下年化Δ为14起点的全期CAGR配对差中位，单位为百分点；A剔除BASE前五赢家，U剔除双方赢家并集。回撤Δ负数表示改善。这些指标沿用现有m2记账，受到下述OI-169/170限制。', '',
      '| 方案 | 年化Δ全 | 年化Δ A | 年化Δ U | 滚5回撤Δ全 | 平均仓位 |',
      '| --- | ---: | ---: | ---: | ---: | ---: |']
    picks=[('low_only','EBDQ30'),('low_only','EBDS03'),('low_only','EBDC30'),
           ('cap','EBQ30'),('cap','EBR20'),('cap','EBFIX160'),('cap','EBFIX100')]
    for stage,arm in picks:
        r=cases[stage,arm]
        text.append(f"| {r['name']} | "+' | '.join(f"{float(r[k]):+.2f}" for k in
                    ('full_cagr_delta_pp','A_cagr_delta_pp','U_cagr_delta_pp','full_roll5dd_delta_pp'))+
                    f" | {float(r['full_exposure_level']):.1%} |")
    text+=['','## 全部相邻档与信号作用','',
           '| 分支 | 参数臂 | 年化Δ全 | 年化Δ A | 年化Δ U | 数值判定 |',
           '| --- | --- | ---: | ---: | ---: | --- |']
    label={'pass':'通过初筛','fail':'未通过','ruling':'需裁定'}
    for (stage,arm),r in cases.items():
        if arm=='BASE':continue
        text.append(f"| {'仅低性价比干预' if stage=='low_only' else '0～160%上限'} | {arm} | "+
            ' | '.join(f"{float(r[k]):+.2f}" for k in ('full_cagr_delta_pp','A_cagr_delta_pp','U_cagr_delta_pp'))+
            f" | {label[r['verdict']]} |")
    text+=['', '绝对利差3pp在2011-11长跑锚点只覆盖2015-05-04～2015-07-31、2018-02-01～2018-02-28两段（合计79个交易日）；正读数不能解释为多次独立验证。2pp档在全样本14路径没有主动减仓，年化与BASE一致，因此数值通过也不代表择时有效。']
    text+=['', '固定160%是每天主动限仓，与现行授信66.6%并不等价：授信限制借款，不能阻止价格变化后被动超仓。低性价比分支在其余时间完整恢复BASE，避免把固定上限效果误归因于股债信号。',
        '仓位上限只约束最大持仓，不强迫满仓；0%意味着卖出可交易持仓、偿债并持有现金，不意味着自动买债。暂停新融资仅用已有现金与后续卖出款还债，不等于当日去掉全部杠杆。',
        '', '## 验证与边界','',
        f"两轮执行{first['executed_paths']+second['executed_paths']}条路径，分别汇总{first['summary_rows']}/{second['summary_rows']}行（包括复用U=A）。两轮BASE全/A各28路径的标准字段复现，输入哈希及生产子集逐行等价验证通过。",
        f"逐日检查覆盖{qa['daily_paths']+qb['daily_paths']}条约束路径，新增约束未产生新的负现金；其余BASE状态仍继承既有资金记账缺陷，不能视为全部资金路径合格。无法满足上限的日数为{qa['unresolved_cap_days']+qb['unresolved_cap_days']}（停牌或无可成交报价会延后，详见逐日诊断）。",
        '新约束的还款与同日对冲融资缺口已修复，并用实际出错历史日期及合成路径验证；被替代作业不作为实验结果。专项及现有执行、尾仓、参数同步和文档审核通过。',
        'OI-169：已有BASE对T+1新建仓首日可能按T日价格记净值。合成例：10万元账户以20元买250股，真实收盘净值10万元，原引擎记9.75万元。本轮收益保持共同记账口径，总仓位守卫另按成交日价格与净资产核验；这些探索性收益读数不能直接作为生产采纳依据。修复与同批重算已登记待处理。',
        '股票净值序列止于2026-08-28，部分原始价格缓存较旧；覆盖分布见manifest.json。指数与债息为供应商当前下载的回溯历史，缺少逐期发布版本核对，尚无新增样本外证据。',
        'OI-170：原引擎部分满额买入未为费用留钱、同日对冲未对现金不足重新提款，会产生未计入融资余额的负现金。高性价比完全恢复BASE时继承该缺陷，停新增融资可能将负余额延续到低状态。约束自身未新产生该赤字，仍须修复基准并重算。',
        '未进入采纳阶段的滑点/K/边际重扫及信号层复核。多起点和滚动窗口相互重叠，不能视为独立试验，也不把历史年化当作未来收益预期。',
        '', '## 证据与复现','',
        '- 首轮完整结果：`data/experiments/exp_equity_bond_20260909/readout.md`。',
        '- 仅低性价比干预：`data/experiments/exp_equity_bond_20260909/high_base/readout.md`。',
        '- 参数、覆盖、尾部、长期锚点、逐年和逐起点指标分别见两目录下的grid.json、signal_coverage.csv、tails.csv、anchors.csv、yearly_overlay.csv、paired_metrics.csv与summary_rows.csv。',
        '- 来源与命令：`data/experiments/exp_equity_bond_20260909/data_sources.md`；有效作业及作废原因见submission.json。']
    out=ROOT/'docs/reports/equity_bond_constraint_2026-09-09.md'
    out.write_text('\n'.join(text)+'\n')
    print(out)


if __name__=='__main__':main()
