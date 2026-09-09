# 融资约束优化研究

结论和数据限制：[研究报告](../../../docs/reports/financing_constraints_2026-09-10.md)。53臂包含当前BASE、无股债约束OFF、固定100%三对照和50个新候选；第一阶段45臂，第二阶段看过结果后追加8个仓位邻居，不属于样本外测试。生产参数沿用E2。

规则先冻结：`preregister.md`、`preregister_refine.md`；唯一信号实现`policy.py`，生产交易执行不变。第二阶段注册器`refine_engine.py`不改第一阶段冻结代码。`manifest.json`和`refine_manifest.json`保存输入哈希、起点、BASE及子集等价证据。

按仓库SLURM规范依次提交：

```bash
sbatch scripts/slurm/equity_bond_opt_20260910.sbatch
# 等第一阶段完成后：
sbatch scripts/slurm/equity_bond_opt_refine_20260910.sbatch
# 等第二阶段完成后：
MPLCONFIGDIR=/tmp/raykey_ebopt_mpl python3 data/experiments/exp_equity_bond_opt_20260910/analyze.py
# 完整性通过后，经唯一入口登记全/A研究摘要（可重复执行）：
python3 data/experiments/exp_equity_bond_opt_20260910/register.py
```

| 产物 | 内容 |
| --- | --- |
| `decisions.csv` | 53臂全/A/U决策读数、初筛和U全面优秀资格；按全期CAGR差排序 |
| `summary_rows.csv`、`refine_rows.csv` | 两阶段逐起点摘要和完整m3窗口序列；第二阶段原样分开保存 |
| `paired_metrics.csv`、`anchors.csv` | 全/A/U全部指标及2009/2011长跑锚点 |
| `report_full_A.txt` | 合并标准报告，完整性先核验，负窗否决按0转正 |
| `policy_history.csv`、`refine_policy_history.csv` | 全历史月度因子、状态、仓位上限与暖机标记 |
| `policy_actual_anchors.csv` | 实际受限日数、主动卖出、平均仓位、未能完成约束的日数 |
| `diagnostic_annual.csv`、`diagnostic_events.csv` | 2011起OFF与当前BASE逐年相对财富、触发及恢复日期 |
| `diagnostic_cycles.csv` | 修复记账后前轮成交周期的摘录；贡献不是CAGR。原件见`exp_ebds03_clause4_20260910/sig/` |
| `verification.json`、`refine_verification.json`、`analysis_verification.json`、`registration.json` | 批次输入、基准复现、完整性与53臂台账登记证据 |

`nav/`、`daily/`、`cache/`及错误日志属于大型可重建产物，不入库。分析程序优先用本轮全精度NAV，并在前轮NAV仍可得时核对到分；成交周期小表作为冻结摘录保留，前轮大文件清理后不伪造重建其归因。

检查：`test_policy.py`（7项）、`test_analysis.py`（3项）、仓库`test_equity_bond_constraint.py`（9项）。OI-172/173的生产实现未改；本批严格拒绝缺起点/窗口，并用0转正语义调用现行判定。仅冻结数据范围已验证，不作为实时信号服务。
