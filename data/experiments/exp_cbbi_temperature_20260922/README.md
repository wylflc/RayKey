# 沪深 300 与六票温度实验

详细解释、公式、温度图、统计和限制见 [研究报告](../../../docs/reports/cbbi_temperature_validation_2026-09-22.zh.md)。

- `config.json` 与 `protocol.md`：预登记及数据完整性修订。
- `inputs/` 与 `input_manifest.json`：冻结输入与来源哈希。
- `coverage.csv`、`bin_summary.csv`、`diagnostics.csv`、`matched_comparisons.csv`、`year_sample_distribution.csv`：当前读数和主/对照检验。
- `corporate_action_audit.csv`、`verification.json`、`causality_checks.json`：含权收益、取数与时间可得性检查。
- `figures/`：7 张完整图、六票总览、前向验证；PNG + 可编辑 SVG。
- `superseded_initial_run/`：发现股改数据缺陷后的初轮留档，不用于正式结论。
- `run_metadata.json`：作业与测试记录；`figure_qa.md`：图形验收。

复现：在仓库根目录提交 `scripts/slurm/cbbi_temperature_20260922.sbatch`（STAGE=run）。它使用冻结输入，重建逐日 CSV、前向明细、图形和审计。STAGE=fetch 会刷新部分输入，只用于另开实验后取数；当前冻结实验不应刷新后仍沿用本轮结论。报告为本次固定结果的解释，不会随重跑自动改写。
