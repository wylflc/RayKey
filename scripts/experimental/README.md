# 实验与核验工具

本目录用于独立回测和诊断。执行要求读取[工作流程](../../docs/000_Ashare_workflow.md) §12；实验配置和结果读取[回测日志](../../docs/Ashare_backtest_log.md)、`data/experiments/` 与 `docs/reports/`。历史实验的参数只用于复现其结果。

## 常设核验入口

| 工具 | 用途 |
| --- | --- |
| `align_buy_line.py` | 对齐买入线合格面；换仓边际按工作流程另行扫描 |
| `selection_edge_audit.py` | 边际选择、排序信息与换仓方向检验 |
| `pv_episode_forward.py`、`rank_episode_forward.py` | P/V 与趋势条件、冻结旧排名表的前向回报；MA60 周期与窗口去重，见[报告](../../docs/reports/pv_episode_review_2026-09-14.zh.md) |
| `panel_tier_forward.py` | 面板估值分档与前向回报 |
| `swap_regime_control.py` | 换仓方向的面板、合成、估值匹配与样本独立性对照 |
| `delta_attribution.py` | 配对差的个股贡献归因 |
| `oi148_slippage_report.py` | 执行成本压力报告 |

## 研究工具索引

| 工具 | 用途 |
| --- | --- |
| `nn_dataset.py`、`nn_train.py`、`nn_apply.py` | 财报特征样本、模型训练与滚动推断 |
| `nn_diagnose_corrected.py`、`nn_panel_apply.py`、`nn_roe.py` | 标签对照、面板内训练与 ROE 预测；`nn_diagnose.py` 仅供原实验复现 |
| `add_growth_path.py` | PEG 并联估值实验 |
| `pit_moat_screen.py`、`pit_moat_rank.py` | 机械阈值和排名的时点筛选实验 |
| `deviation_gate_diagnostics.py` | 偏离度闸门诊断 |
| `decompose_pv_bias.py`、`calibrate_band_by_group.py`、`calibrate_band_ma60.py`、`calibrate_band_zscore_partial.py` | 估值偏差分解与校准实验 |
| `moat_param_lab.py` | 单票估值参数与前向回报比较 |
| `reconstruct_holding_weights.py`、`drawdown_path.py` | 逐笔流水、持仓权重与回撤归因 |
| `build_cap_rank_universe.py`、`subset_daily_states.py` | 指数类股票库、抽样面板与状态子集 |
| `vp_signal_lab.py` | 量价事件研究与组合模拟；依赖 NumPy |
| `value_procyclicality.py`、`cycle_peak_buy_audit.py` | 估值顺周期与盈利高点买入核查 |
| `trough_guard_review.py`、`trough_guard_checks.py`、`trough_guard_evidence.py` | 谷底守卫复测，见[报告](../../docs/reports/trough_guard_review.zh.md) |
| `whipsaw_joint_run.py`、`whipsaw_joint_diag.py`、`whipsaw_joint_validate.py`、`whipsaw_joint_census.py`、`whipsaw_joint_signal_audit.py` | MA20 震荡与重复换仓核验，见[报告](../../docs/reports/whipsaw_joint_review.zh.md) |

## 使用约束

- 命令参数读取对应脚本的 `--help`；生产参数读取工作流程，基准配置读取 `sweep_backtest_configs.py`。
- 回测与扫描通过 `scripts/slurm/` 提交；资源要求读取[代理规则](../../CLAUDE.md)。
- 实验输出使用独立目录，不覆盖生产文件；先验证子集或替代输入与所需宇宙的等价性。
- 生产脚本的实验开关仅在实验命令中显式传入。采纳须完成工作流程的验证与裁定。
- 完整实验代码保留用于复现；清理派生产物使用 `clean_derived_artifacts.py` 的预览清单。
