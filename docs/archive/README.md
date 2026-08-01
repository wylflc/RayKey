# 归档：已完成的过程记录

本目录存放**已完成工作的过程记录与一次性审计**。它们记录了当时如何做出判断，但
**不再是任何流程的输入**——放在 `docs/` 主目录会被后续分析误当作现行口径。

生效标准只在 `docs/000_Ashare_workflow.md` 与 `docs/000_personal-investment-system-v1.zh.md`。

| 文件 | 内容 | 归档理由 |
| --- | --- | --- |
| `round1-rescan-progress.md` | 全市场第一轮三类初筛的进度与交接（5,653 家） | 该轮已于 2026-07-09 完成，结果沉淀在 `a_share_watchlist_quality_tiers.csv` 与 `attention_class`；本文件是过程日志 |
| `Ashare_workflow_diagnostic_report_20260714.md` | 2026-07-14 对工作流的只读审计 | 结论已在 v18-v29 期间吸收；此后工作流已迭代至 v1.35，报告描述的机制多数已被替换 |
| `Ashare_instruction_audit_20260731.md` | 2026-07-31 指导性文档审计（skill 复述阈值问题） | 结论已实施：skill 全部改为路由、`strategy-taxonomy.md` 由重编码改为指针 |

同类归档：`data/archive/completed-queues/`（已跑完的工作队列）、
`data/archive/2026-06-two-layer-review/`（2026-06 两层复核轮的最终产物）。

**未归档的设计文档**（`Ashare_tiering_v2_design.md`、`Ashare_valuation_v2_design.md`）
留在 `docs/` 主目录：它们标注为「已实施」但仍是**决策审计轨迹**，记录每项参数为何取
当前值，修订时需要回看。
