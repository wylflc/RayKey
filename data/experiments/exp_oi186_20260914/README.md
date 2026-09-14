# OI-186 确认成交冷却

规则唯一入口：工作流 §9.3.3，成交操作入口：§11.5；本目录是验证证据。

- `preregister.md`：轨道 A、冻结两臂及检查设计。
- `manifest.json`：最终作业输入哈希、面板子集等价性、296 股行情末日。
- `legacy_reproduction.json`：旧模式锚点 48 个字段及窗口序列复现。
- `verification.json`、`guardrails.csv`：四档成本、全/A/U配对校验；U=A复用。
- `report_full_A_0.txt`：零滑点标准报表；其余三个报表为成本压力。
- `summary_rows.csv`、`paired_metrics.csv`：完整摘要及同起点同窗配对。
- `unit_tests.txt`、`failure_tests.txt`：89 项 unittest 与 9 项失败语义检查。
- `state_migration.json`：真实空计数迁移，无实际成交登记。
- `initial_registration.json`、`registration.json`：28 BASE 摘要以 lrc3 重登及最终幂等校验，旧台账键保留。
- `validation_revision.json`：成本验证发现并撤回的零股换仓附带变化，不属于最终修复。
- `resource_usage.json`：最终 SLURM 作业 26680547，7 分 30 秒，32 CPU。

重现配对运行 `sbatch --account=tes21035 scripts/slurm/oi186_cooldown_20260914.sbatch`，完成后运行本目录 `post/analyze.py`；确认输入与最终检查后才运行 `post/register.py`。逐路径缓存、净值、统计和流水可重建，不入 Git。历史输入有变化时须建立新批次，不能覆盖本批证据。
