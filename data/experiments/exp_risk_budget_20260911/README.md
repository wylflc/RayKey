# 风险预算回测（2026-09-11）

本轮验证当前C030R35基准上的持仓压力预算、波动率目标与固定仓位对照。
规则和网格只认[预登记](preregister.md)与[grid.json](grid.json)，不修改生产BASE。
前置诊断见[大回撤报告](../../../docs/reports/drawdown_review_2026-09-11.zh.md)。

**结果：12候选均未通过收益保留要求，U资格0；不修改生产。** 实际执行574条正式路径，
644条摘要含70条同剔除集复用记录。完整结论见[回测报告](../../../docs/reports/risk_budget_backtest_2026-09-11.zh.md)。

```bash
sbatch --account=tes21035 --time=00:10:00 --export=ALL,RISK_PILOT=1 scripts/slurm/risk_budget_20260911.sbatch
sbatch --account=tes21035 --export=ALL,RISK_PILOT=0 scripts/slurm/risk_budget_20260911.sbatch
python3 data/experiments/exp_risk_budget_20260911/report.py
python3 data/experiments/exp_risk_budget_20260911/followup_cost.py
python3 data/experiments/exp_risk_budget_20260911/audit_run.py
python3 data/experiments/exp_risk_budget_20260911/register.py
python3 data/experiments/exp_risk_budget_20260911/plot.py
python3 data/experiments/exp_risk_budget_20260911/build_report.py
```

已有manifest时不重新prepare；原始数据及执行源码变动会拒绝复跑。`run.one`只在输入核验后
复用同标签完成产物；若要强制重算，保留原证据后另建实验目录，不混入当前批次。
`followup_cost.py`本批不启动新路径；未来若有通过候选，其并行补跑须通过SLURM，
然后重出report。原冻结副本可按上轮verification所列Git提交重建。

`policy.py`只用截至信号日的信息计算新上限；`engine.py`在内存安装观察器和约束适配，
调用原引擎完整交易路径。`BASE`完全不安装适配器，`OFF`安装但返回无新增约束，
两者小样本须与原基准逐日一致。所有候选使用自身持仓反馈，不套用BASE事后权重。

`manifest.json`冻结数据、实际使用的历史副本与执行代码；`repair_log.json`记录实现修复。
`raw/`含逐路径净值、风险日记、合并约束流水、原始摘要，忽略入库。
`summary_rows.csv`保留所有全/A/U与成本摘要；`verification.json`记录路径完整性和基准复现。
`decisions.csv`使用成文的负窗“0转正”口径，同时保留正式判定器旧结果核对；
`standard_metrics.csv`、`tails.csv`、`anchors.csv`、`annual_paths.csv`保留标准读数和分段证据。
`same_interval_events.csv`同时给BASE固定峰谷损失，避免用候选不同日期的MDD冒充该段改善；
其中`recovered_after_base_trough`仅表示BASE谷日以后首个不低于候选在BASE峰日净值的日期，
不等于候选自身全部独立回撤的恢复日期。`risk_activity.csv`给实际触发、仓位与覆盖。

`own_episodes.csv`保留每路径最深三段独立回撤与峰至恢复自然日数；
`fixed_control_comparisons.csv`逐起点直接比较各风险臂与三档固定上限；
`cost_effects.csv`比较30bp与自身0bp；`coverage_by_year.csv`记录逐年观测缺失。
`execution_checks.json/csv`核对净值、资金、信号时序、日末上限与引擎未满足记录；
`constraint_exceptions.csv`保留555个路径日的停牌/无报价超限，不能作为严格每日上限保证。
压力预算造成的实际情景损失偏差另计在execution_checks.csv，不与总仓位超限混为一谈。
正式作业26572140完成（16分17秒，MaxRSS约16.36GiB）；工程小样本26572119通过。

汇总登记只走`clean_derived_artifacts.write_ledger`，原BASE标准摘要不覆盖。
`registration.json`记录574个新增键、41个台账臂名（含全/A/U及成本）、原值保留检查。
