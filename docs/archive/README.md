# 归档：已完成的过程记录

本目录存放**已完成工作的过程记录与一次性审计**。它们记录了当时如何做出判断，但
**不再是任何流程的输入**——放在 `docs/` 主目录会被后续分析误当作现行口径。

生效标准只在 `docs/000_Ashare_workflow.md` 与 `docs/000_personal-investment-system-v1.zh.md`。

| 文件 | 内容 | 归档理由 |
| --- | --- | --- |
| `round1-rescan-progress.md` | 全市场第一轮三类初筛的进度与交接（5,653 家） | 该轮已于 2026-07-09 完成，结果沉淀在 `a_share_watchlist_quality_tiers.csv` 与 `attention_class`；本文件是过程日志 |
| `Ashare_workflow_diagnostic_report_20260714.md` | 2026-07-14 对工作流的只读审计 | 结论已在 v18-v29 期间吸收；此后工作流已迭代至 v1.35，报告描述的机制多数已被替换 |
| `Ashare_instruction_audit_20260731.md` | 2026-07-31 指导性文档审计（skill 复述阈值问题） | 结论已实施：skill 全部改为路由、`strategy-taxonomy.md` 由重编码改为指针 |
| `Ashare_tiering_v2_design.md` | 质量分级 v2 的需求、冲突分析与三档收敛过程 | 2026-08-01 已并入工作流 v1.27；文件自述「它不是标准」。**v2.00 归档**：其生效内容全部在工作流 §5.7 与 §6.2，留在 `docs/` 主目录只会被误读为现行口径 |
| `Ashare_valuation_v2_design.md` | 估值类型学与建带规范 v2 的诊断证据与方案 | 2026-08-01 已并入工作流 v1.28；文件自述「它不是标准」。**v2.00 归档**：其核心成果（十一类锚定量分类、关闭档位反推带）已在工作流 §6.5 与 §6.6，而它描述的**通用建带公式已于 v2.00 整体退役**（全池 261 家逐票建档），继续留档会与现行口径直接冲突 |
| `moat-scoring-rubric.md` | 0-100 七维加权护城河打分口径（英文） | A 股自 2026-07-08（ADR-0006）起已不用它；此后仅服务港股/美股全覆盖打分脚本，而该管线已随 `scripts/archive/` **v2.00 整体退役**（海外覆盖改为 §6.8 点名清单）。**现无任何在用流程引用本文件** |
| `Ashare_pit_judgment_protocol.md` | 时点关注度判定协议（逐股逐报告期、前视隔离、退市处置、重述污染） | **2026-08-24 归档**：判定轮 2026-08-12 完成、退市股二遍盲判 08-21 完成（OI-040 结案），回测宇宙固定为 `panel_moat_bank_v6b.csv`；中间产物在 `data/archive/pit-judgment-2026-08/`。需要重开判定时按本协议 §12 |
| `Ashare_backtest_log_2026-08-10_to_2026-08-24.md` | 回测日志旧纪元 §12.5~§12.125（v4.66 以前） | 2026-09-05 自 `Ashare_backtest_log.md` 移出；读数不与现行基准配对 |
| `Ashare_workflow_changelog_v1.00-v4.65.md` | 版本记录 v1.00~v4.65 各行 | 2026-09-05 自 `Ashare_workflow_changelog.md` 移出 |
| `backtest_candidate_strategies.md` | 2026-08-08 登记的「多起点检验后成立、待用户裁定」的回测配置 | **v2.97 归档**：其中的候选此后已全部裁定完毕（相关性 0.85、一档 1.0%、换仓 0.15、建仓日 MA20 止损均已进当时的 §9.7.1（现 §9.3.1）；止损「无」那一条已被 §12.20.3 翻转），而它的全部年化数字产生于「今日 261 池」，早于时点面板、λ=2.0、银行股利折现与 V3/V4 三次换宇宙。留在 `docs/` 主目录会被误读为「尚有待裁定的候选」。现行基准只在 §9.3.1.2 |

**旧正文全文快照不再入库**（2026-08-24 起）：`Ashare_workflow_v2.56_full.md` 与 `personal-investment-system_v1.20_full.md` 已删除，
需要时用 `git show 5fa8ad69:docs/archive/<文件名>` 取回；两份 000_ 文档的逐版变化见 `docs/Ashare_workflow_changelog.md` 与 `personal-investment-system-history.md`。

同类归档：`scripts/archive/`（已退役的脚本）、`data/archive/completed-queues/`（已跑完的工作队列与复核记录）、
`data/archive/pit-judgment-2026-08/`（时点判定的中间产物与面板世系）、`data/archive/2026-06-two-layer-review/`（2026-06 两层复核轮的最终产物）、
`data/archive/daily_scan_log_2026-07-10_to_2026-08-10.md`（旧账户纪元的每日扫描日志）、`data/archive/pretrade_decisions_2026-08-03.csv`（v2.05 退役的买前裁决记录）。

**唯一未归档的附属文档**是 `docs/Ashare_quality_rubric.md`——它不是设计文档而是**在用细则**：
§5.7 定档所依赖的 Q1/Q2 1 分粒度载体硬度阶梯只在那里，工作流按 §5.7 显式引用它。
规则性内容（参考分公式、旗标表、评分硬约束、输出字段）已上收至工作流 §5.7，
该文件此后只承担**打分口径与判例证据**。
