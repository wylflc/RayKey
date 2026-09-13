# OI-174 剩余候选对新 BASE 的资格复核（2026-09-13，轨道 B）

规则与结论见回测日志 §12.234；预登记 `preregister.md`。候选规则沿用 `../exp_equity_bond_opt_20260910/policy.py` 的冻结实现（`engine.py` 只做适配），输入与 `../exp_oi167_land_20260913` 登记跑完全相同（面板子集状态、冻结参考表），BASE 28 条逐位复现。

| 文件 | 内容 |
| --- | --- |
| `grid.json`、`manifest.json`、`policy_history.csv` | 8 臂规格、输入哈希与等价证据、逐月信号状态 |
| `sweep_full.txt`、`sweep_A.txt`、`sweep_full_A.txt`、`report_full_A.txt` | 全/A 扫描与标准报表（U=A 复用） |
| `decisions.csv`、`paired_metrics.csv`、`anchors.csv`、`winner_sets.json` | 第 2 款判定、第 4 款 U 资格、全部配对读数与长跑锚点 |
| `summary_rows.csv`、`verification.json`、`analysis_verification.json`、`registration.json` | 336 行摘要、完整性核验、台账登记（`OI174REQ20260913_REQ*`） |

`cache/`、`nav/`、`daily/`、`errors/` 为可重建大产物，不入库。作业 26654814（64 核、4 分 15 秒、峰值 21.6 GiB），在 scratch 克隆上运行（`RAYKEY_ROOT`）。
