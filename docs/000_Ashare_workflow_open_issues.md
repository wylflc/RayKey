# A 股工作流待处理事项

登记已确认的流程缺陷与用户要求的待办；每项标明类别、证据、影响、所需动作及完成条件，按发现日倒序排列，每项使用三级标题。编号连续。

完成后，规则变化写入 `Ashare_workflow_changelog.md`，实验依据写入 `Ashare_backtest_log.md` 或报告，编号与处置移入 `Ashare_workflow_open_issues_closed.md`；此处只保留未完成项。

## 待处理（3 项）

### OI-195｜§9.1 人工步骤无脚本承载，月度日志归档已滞后（2026-09-19）

- **类别**：流程缺陷（执行留痕）。
- **证据**：§9.1 第 6 步要求每月首个扫描日把「上月以前」的条目归档，`data/archive/` 最新归档止于 2026-08-30，而 `docs/000_daily_scan_log.md` 第 1270 行仍是 2026-08-31 条目；「上月以前」的边界未定义。§10.3 `strategy_return_tracker.py --write`、§2 决策日志换纪元移档、§9.1 第 3 步除权登记均为人工步骤，`daily_execution_guard.py verify` 与发布凭据不核验其完成（`grep daily_scan_log_\|decision_log_ scripts/` 只命中索引读取器）。
- **影响**：阅读日志持续膨胀（当前 1,340 行）、归档边界因人而异；策略收益列漏算或漏跑不会被凭据拦截。
- **动作／完成条件**：裁定归档边界的精确口径（建议：信号日早于本月 1 日的全部条目）并补归档 08-31 条；把 `strategy_return_tracker.py --check` 纳入 verify 或在 §9.1 第 6 步显式列为发布前检查。以归档止日与日志最早条目相接、verify 覆盖收益列为完成条件。

### OI-194｜§2 唯一真值表未覆盖若干生产产物（2026-09-19）

- **类别**：文档缺陷。
- **证据**：脚本写出但 §2 未列——`daily_buy_candidates.csv`（仅 §8.2 提及）；发布凭据 `daily_execution_publication.json`（§9.1 称「成功凭据」，全文无路径，缺省落点见 `daily_execution_guard.py:262`）；`data/interim/daily_evidence_<日期>.json` 与 `daily_{announcements,corporate_actions,market_context}_<日期>.json`；§6.7 逐日状态与带（`a_share_daily_states_{adopted,hold,b2}.csv`、`roic_bands(_b2).csv`、`roic_daily_raw(_b2).csv`、`a_share_pool_model_bands_b2.csv`）；`a_share_focus_watchlist_l1_l2_valuation.csv`；人工台账 `entity_reset_dates.csv`／`share_event_reviews.csv`（§6.5.2.4）；`overseas_watchlist_valuation.csv`（§6.8）；`pit_attention/panel_moat_bank_v6b.csv`；`shadow_portfolio/`；`a_share_company_analysis_index.csv/.md`（生成脚本 `build_a_share_company_analysis_index.py` 在工作流全文未被引用）。
- **影响**：§2 自称唯一真值表却不完整，发布凭据的路径无处可查。
- **动作／完成条件**：补行，或在 §2 声明只覆盖每日执行真值并指向 §6.7／§6.8／§10.4；`audit_repository_docs.py` 增加「脚本写出的 `data/processed` 路径须在工作流出现」检查。以该检查通过为完成条件。

### OI-193｜工作流内阈值多处成文，违反「同一口径只定义一次」（2026-09-19）

- **类别**：文档缺陷（§1 第 6 条）。
- **证据**（`docs/000_Ashare_workflow.md` 行号）：130% 强平线见第 20、657、714 行，家在个人投资体系 §4；66.6% 授信见第 657、714、717 行，家在 §10.2；股债 3%／30%／3.5% 见第 630 行（§9.3.1）与第 866 行的 `BASE` 字面参数（§9.3.1.2 规定 `BASE` 只落在 `sweep_backtest_configs.py`）；45 天观测过期见第 337、630 行与 §12.1；252 日相关性见第 82、551、625 行；2025-01-01 陈旧带门槛见第 293、301 行。个人投资体系、评分细则、README 与 CLAUDE.md 无复写。
- **影响**：改阈值需同步多处，漏改即在工作流内部自相矛盾。
- **动作／完成条件**：数值只留 §9.3.1／§10.2／个人投资体系 §4 一处，其余改为章节引用（§12.1 研究段引用不复写）。完成条件：每个阈值在工作流正文只出现一次，`audit_repository_docs.py` 通过。

