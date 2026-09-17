"""Readable report; all numeric claims come from paired, validated paths."""
import csv
import json
import statistics as st
from collections import defaultdict
from run import EXP, ROOT, sw


def read(name):
    with (EXP/name).open() as f: return list(csv.DictReader(f))


def main():
    v=json.loads((EXP/'verification.json').read_text())
    mech=json.loads((EXP/'mechanism_verification.json').read_text())
    winners=json.loads((EXP/'winner_sets.json').read_text())
    manifest=json.loads((EXP/'manifest.json').read_text())
    idx={(r['group'],r['arm'],r['metric']):r for r in read('paired_metrics.csv')}
    paths=read('summary_rows.csv'); anchors=read('anchors.csv')
    def level(g,a,k,scale=100): return float(idx[g,a,k]['level_median'])*scale
    def delta(g,k,scale=100): return float(idx[g,'REPEAT',k]['paired_delta_median'])*scale
    def table(headers,rows):
        return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                         ['| '+' | '.join(map(str,r))+' |' for r in rows])
    labels={'full':'全样本','A':'剔除BASE前五赢家 A','U':'剔除两臂赢家并集 U'}
    decisions=[]
    for g,label in labels.items():
        negative={(r['arm'],r['start']):float(r['滚动5年为负的窗口占比'])
                  for r in paths if r['group']==g}
        flips=sum(negative['BASE',s]==0 and negative['REPEAT',s]>0 for s in sw.DEFAULT_STARTS)
        decisions.append([label,f'{delta(g,sw.WIN5_KEY):+.2f}pp',
            f'{idx[g,"REPEAT",sw.WIN5_KEY]["positive_starts"]}/14',f'{level(g,"BASE","年化"):.2f}%',
            f'{level(g,"REPEAT","年化"):.2f}%',f'{delta(g,"年化"):+.2f}pp',
            f'{idx[g,"REPEAT","年化"]["positive_starts"]}/14',f'{delta(g,"滚动5年年化P25"):+.2f}pp',
            f'{delta(g,"滚动5年回撤中位"):+.2f}pp',f'{flips}/14'])
    text=['# 同一候选连续触发换仓的回测（2026-09-17）','','## 决策读数','',
        '只移除每个未持仓候选每天只触发一次卖出的循环限制。成功卖出后，如果资金仍不足一档，'
        '继续用同一候选选择下一只来源；同一来源仍最多减一档。买入、融资、止损、费税等沿用BASE。','',
        table(['样本','滚5同窗年化配对差','同窗改善起点','BASE全期年化中位','REPEAT全期年化中位','全期年化配对差',
               '年化改善起点','滚5 P25配对差','滚5回撤中位配对差','负窗0转正起点'],decisions),'',
        '配对差先按同一起点相减再取中位；主读数先对齐同一窗口，窗口内作差后按起点取中位。'
        '两列水平中位之差不等于配对差。回撤用正值列示，负差表示改善。','',
        '## 采纳判定','',f'轨道B筛查：**{v["verdict"]}**。'+'；'.join(v['reasons'])+'。',
        '全样本的主读数与全期年化均下降，A/U去赢家样本的年化则提高，说明改动的效果依赖股票池。'
        '风险闸门未触发，但全样本收益损失已超过采纳容忍范围。',
        f'去赢家全面优秀：{"是" if v["U_excellent"] else "否"}。本次只有1个候选臂，未选取最优参数。'
        '本批为用户要求的单机制对照，未修改生产策略或已发布的交易清单。','',
        '## 跨起点尾部','']
    tails=[]
    for g in labels:
        for arm in ('BASE','REPEAT'):
            rs=[r for r in paths if r['group']==g and r['arm']==arm]
            worst=min(rs,key=lambda r:float(r['滚动5年年化最差']))
            draw=max(rs,key=lambda r:float(r['最大回撤']))
            margin=min(rs,key=lambda r:float(r['最低担保比例']))
            buffer=min(rs,key=lambda r:float(r['最低股票同跌缓冲']))
            cash=min(rs,key=lambda r:float(r['最低现金']))
            tails.append([labels[g],arm,f'{float(worst["滚动5年年化最差"])*100:.2f}%（{worst["start"]}；末窗{worst["滚动5年年化最差窗口末日"]}）',
                f'{float(draw["最大回撤"])*100:.2f}%（{draw["start"]}；{draw["最大回撤起日"]}—{draw["最大回撤止日"]}）',
                f'{float(margin["最低担保比例"])*100:.2f}%（{margin["start"]}；{margin["最低担保比例日"]}）',
                f'{float(buffer["最低股票同跌缓冲"])*100:.2f}%（{buffer["start"]}；{buffer["最低股票同跌缓冲日"]}）',
                f'{float(cash["最低现金"]):.2f}（{cash["start"]}；{cash["最低现金日"]}）',
                sum(int(r['负现金日数']) for r in rs),
                f'{sum(int(r["强平次数"]) for r in rs)}/{sum(int(r["强平次数"])>0 for r in rs)}',
                f'{sum(float(r["滚动5年为负的窗口占比"])>0 for r in rs)}/14',
                f'{min(float(r["rf覆盖率"]) for r in rs)*100:.2f}%',max(r['末次净值日'] for r in rs)])
    text += [table(['样本','臂','最差滚5及起点/末日','最深回撤及起点/区间','最低担保及起点/日期',
        '最低股票缓冲及起点/日期','最低现金及起点/日期','负现金日数','强平次数/起点','出现5年亏损起点','最低rf覆盖','数据末日'],tails),'',
        '以下为附表，除工作流规定的五项决策读数外，其余只作描述。','',
        '## 附表：收益、风险、换手和集中度','']
    metric_groups=[('标准收益风险指标',[
        ('滚动5年年化中位',100,'%'),('滚动5年年化P25',100,'%'),('滚动5年年化最差',100,'%'),
        ('滚动5年回撤中位',100,'%'),('滚动5年Calmar中位',1,''),('滚动5年Sharpe中位',1,''),
        ('滚动5年为负的窗口占比',100,'%'),('年化',100,'%'),('最大回撤',100,'%'),('Calmar',1,''),('Sharpe',1,''),
        ('互不重叠5年块中位',100,'%'),('滚动3年年化中位',100,'%'),('滚动3年回撤中位',100,'%'),
        ('逐年收益中位',100,'%'),('逐年最差',100,'%'),('年均换手',1,'倍'),('平均仓位',100,'%')]),
        ('集中度及滚动10年', [('持仓数中位',1,'只'),('单票权重中位',100,'%'),('单票权重P90',100,'%'),
        ('单票权重最大',100,'%'),('前三权重中位',100,'%'),('单票超60%天数占比',100,'%'),('滚动10年年化中位',100,'%')])]
    for title,metrics in metric_groups:
        text+=['### '+title,'']
        for g,label in labels.items():
            rows=[]
            for k,scale,unit in metrics:
                rows.append([k,f'{level(g,"BASE",k,scale):.2f}{unit}',f'{level(g,"REPEAT",k,scale):.2f}{unit}',
                    f'{delta(g,k,scale):+.2f}'+('pp' if scale==100 else unit),
                    f'{idx[g,"REPEAT",k]["positive_starts"]}/14'])
            text += ['**'+label+'**','',table(['指标','BASE水平中位','REPEAT水平中位','配对差中位','差为正起点'],rows),'']
    text += ['## 附表：两个300万元空仓启动的长跑锚点','']
    rows=[]
    for g in labels:
        for start in ('2009-11-01','2011-11-01'):
            a={r['arm']:r for r in anchors if r['group']==g and r['start']==start}
            for arm in ('BASE','REPEAT'):
                r=a[arm];b=a['BASE']
                rows.append([labels[g],start,arm,f'{float(r["final_equity"])/10000:,.2f}',
                    f'{float(r["cagr_pct"]):.2f}%',f'{float(r["cagr_pct"])-float(b["cagr_pct"]):+.2f}pp',
                    f'{float(r["mdd_pct"]):.2f}%',f'{float(r["mdd_pct"])-float(b["mdd_pct"]):+.2f}pp',
                    f'{r["buys"]}/{r["sells"]}',f'{float(r["average_holding_days"]):.1f}'])
    text += [table(['样本','起点','臂','期末净资产/万元','年化','年化差','最大回撤','回撤差','买入/卖出笔数','平均持有天数'],rows),'',
        '## 附表：连续触发机制审计','']
    rows=[]
    for r in mech['groups']:
        rows.append([labels[r['group']],r['arm'],r['median_swap_sales'],r['median_repeated_target_days'],
            r['extra_source_sales_sum'],f'{r["extra_sales_tiny_gap_fraction"]*100:.2f}%',r['maximum_sources_per_target']])
    text += [table(['样本','臂','换仓卖出笔数中位','多来源触发日数中位','同候选额外卖出合计','额外卖出中缺口≤1%一档比例','同候选最多来源数'],rows),'',
        '每笔连续卖出前均重新检查原资金及边际条件；已验证同一来源当日最多出现一次、无零股卖出。'
        '额外卖出是相对该候选当日第一笔而言，不等于与BASE路径逐笔相减；不同启动路径共享历史，合计笔数不是独立样本数。','',
        '连续触发存在整档卖出效应：即使只差少量资金才能凑足一档，下一只合格来源仍按原规则减一档，'
        '不会仅按资金缺口卖出。上表列出了缺口不超过一档1%的额外卖出比例；这是机制诊断，'
        '尚未单独分解它对收益差的贡献，不能把全部收益变化归因于这一项。','',
        '### 9月17日账户的离线机制示例','',
        '使用当天已发布信号和账户快照，仅在内存中替换扫描循环：原规则只列卖出牧原1,700股；'
        '连续触发版还会由成都银行触发卖出电投能源4,500股。合并卖出款先弥补资金缺口，'
        '再按全部合格标的的原P/V顺序分配，得到中材国际16,200股的未计费买入上限。'
        '这说明触发者仍不等于最终买入者。本例未计费，不是新的下单清单，所有正式发布文件保持原样。'
        '详见[离线对照](../../data/experiments/exp_swap_repeat_candidate_20260917/today_counterfactual.json)。','',
        '## 数据与复现','',
        f'- 正式路径{v["paths"]}条，全/A/U同起点同窗口完整配对，负现金日数0。',
        f'- 原生与记录版烟测一致；当前BASE的全/A共28条路径与前次基准比较，指标/窗口字段差异为{v["baseline_reference_differences"]}项。',
        '- 历史价格末日：'+'、'.join(f'{n}只截至{d}' for d,n in sorted(manifest['price_end_counts'].items()))+'。净值末日为2026-08-28；未刷新历史行情，不代表截至9月17日的市场表现。',
        '- 状态子集沿用已有逐行等价证据并校验生产/子集/面板哈希。两臂使用相同输入，运行前后指纹一致。',
        '- 本金300万元，费税及融资利息计入，滑点0bp；期末资产含剩余持仓，未假设额外清仓费用。',
        f'- 剔除集A：`{",".join(winners["A"])}`；U：`{",".join(winners["U"])}`。'+('U=A，复用。' if winners['U_reused_A'] else 'U单独重跑两臂。'),
        '- 多起点共享终点、滚动窗口相互重叠；收益受历史股票池及长期研究选择影响，不把高历史年化作为未来承诺。','',
        '```bash',
        'sbatch --account=tes21035 --cpus-per-task=16 --export=ALL,STAGE=smoke scripts/slurm/swap_repeat_candidate_20260917.sbatch',
        'sbatch --account=tes21035 --export=ALL,STAGE=scan scripts/slurm/swap_repeat_candidate_20260917.sbatch',
        'python3 data/experiments/exp_swap_repeat_candidate_20260917/analyze.py',
        'python3 data/experiments/exp_swap_repeat_candidate_20260917/diagnose.py',
        'python3 data/experiments/exp_swap_repeat_candidate_20260917/render.py','```','',
        '[预登记](../../data/experiments/exp_swap_repeat_candidate_20260917/preregister.md) · '
        '[完整摘要](../../data/experiments/exp_swap_repeat_candidate_20260917/summary_rows.csv) · '
        '[配对指标](../../data/experiments/exp_swap_repeat_candidate_20260917/paired_metrics.csv) · '
        '[核验记录](../../data/experiments/exp_swap_repeat_candidate_20260917/verification.json) · '
        '[连续触发明细](../../data/experiments/exp_swap_repeat_candidate_20260917/repeated_trigger_examples.csv)','']
    path=ROOT/'docs/reports/swap_repeat_candidate_2026-09-17.zh.md'
    path.write_text('\n'.join(text))
    print(path)


if __name__=='__main__': main()
