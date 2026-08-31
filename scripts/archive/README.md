# 归档：已退役的脚本

本目录存放**不再属于任何现行流程**的脚本。它们能跑，但没有任何一条现行口径调用它们，
放在 `scripts/` 主目录会被后续分析误当作在用工具。

判定标准（三条同时成立才归档）：①`docs/000_Ashare_workflow.md` 未引用；②无其他脚本 import；
③其产物已被现行产物取代或所属轮次已结束。

需要恢复时直接 `git mv` 回 `scripts/` 即可，无路径依赖。

**三个月规则（用户 2026-08-14 定）**：归档满三个月仍未被取回的，直接永久删除。
「可永久删除日」列即该日期，到期前请先确认表中「现行替代」一栏仍然成立。

| 脚本 | 归档日期 | 可永久删除日 | 退役理由 | 现行替代 |
| --- | --- | --- | --- | --- |
| `fetch_hong_kong_universe.py`<br>`fetch_hong_kong_research_evidence.py`<br>`run_hong_kong_full_coverage_scoring.py`<br>`fetch_us_universe.py`<br>`fetch_us_research_evidence.py`<br>`run_us_full_coverage_scoring.py` | 2026-08-02 | 2026-11-02 | **港股/美股全覆盖打分管线整体退役**。其口径 `docs/moat-scoring-rubric.md` 自 2026-07-08（ADR-0006）起已被 A 股撤出，此后只服务这六个脚本；而海外覆盖已于 v1.22 改为 §6.8「海外关注清单」——只对**用户点名**的公司按 §5.7 分层、§6.5 定带，不做全市场打分。产物 `data/interim/{hong_kong,us}_*.csv` 停在 2026-05-14 | 工作流 §6.8 + `data/processed/overseas_watchlist_valuation.csv` + `scripts/overseas_quotes.py` |
| `build_a_share_full_rescan_queue.py` | 2026-08-02 | 2026-11-02 | 全市场第一轮三类初筛重扫的工作队列生成器。该轮已于 **2026-07-09 完成**（5,653 家：261 worth_attention / 5,332 boundary_pending / 60 garbage），队列不再需要重建 | 季度审查走 `build_quarterly_quality_review_queue.py`（§5.3）；全量重扫见 OI-036 |
| `fetch_a_share_research_evidence.py` | 2026-08-02 | 2026-11-02 | 早期研报证据抓取，产物 `a_share_research_queue.csv` 停在 2026-05-14（已删除），且其字段口径不含建带所需的一致预期覆盖机构数 | `fetch_a_share_valuation_evidence.py`（§6.3 一致预期覆盖机构数由它产出） |
| `apply_evidence_review.py` | 2026-08-02 | 2026-11-02 | 2026-08-01 分层证据复核轮的一次性回写工具，该轮已闭环（261 家全部 evidence-reviewed），复核记录见 `data/archive/completed-queues/evidence_review_log.md` | 无——后续分层变更走 §7.2 质量复核触发，逐票写入 |

| `build_pit_judgment_queue.py`<br>`fetch_delisted_financials.py` | 2026-08-14 | 2026-11-14 | **OI-040（幸存者偏差）配套的两个工具**。该轮已查实为**不可测的数据缺口**——本地行情与财务两侧均不含退市公司，九只已知退市股五项数据全缺，`data/raw/ohlcv` 的 5,210 个文件无一在 2026 年前终止。**队列造不出来、退市财务也补不齐**，两个脚本因而无对象可跑 | 无。OI-040 已于 2026-08-21 结案（回测日志 §12.106），协议在 `docs/archive/Ashare_pit_judgment_protocol.md` |
| `fetch_sina_original_financials.py` | 2026-08-14 | 2026-11-14 | 取原始披露口径财务以对冲东财的追溯重述污染。**该问题仍未验证**（登记在 §12.39 的效力边界里），但本脚本自 2026-08-11 起未再被任何口径调用 | 无现行替代。**若日后要查重述污染，从这里恢复**，不要重写 |
| `fetch_hk_annual_financials.py` | 2026-08-14 | 2026-11-14 | 港股逐年财务抓取。§6.8 海外关注清单只对**用户点名**的公司逐票定带，取数走 `overseas_dossier_inputs.py`，本脚本的全量年度指标无处消费 | `scripts/overseas_dossier_inputs.py` + `scripts/overseas_quotes.py`（§6.8） |
| `cleanup_dossier_implied_growth_oi078.py` | 2026-08-21 | 2026-11-21 | **OI-078 的一次性回写工具**（v4.30 已执行）：把 `a_share_valuation_dossiers.csv` 的 `implied_growth_years` 178 份旧口径文本按句清理为只含手写可证伪命题；规则与人工核定项都在脚本里，清理前原文在 git 父提交 | 无——第八节首段此后由 `build_company_dossier_readmes.py` 机械生成，手写列不再承载带值 |
| `measure_pool_selection_bias.py` | 2026-08-14 | 2026-11-14 | 2010 年时点名单「进池 vs 未进池」此后收益的一次性度量，结论已写入 §12.25 并转为 OI-040 | 无——一次性度量，结论已沉淀 |
| `build_metric_states.py` | 2026-08-16 | 2026-11-16 | §12.61「每只股票只跟自己比」实验的指标层（pb／pe／pbroe 逐日状态，产物 `data/processed/metric_states/` 已随清理删除） | 无——§12.61 结论：自身分位无前瞻信息 |
| `fix_panel_entry_lookahead.py` | 2026-08-16 | 2026-11-16 | 把 v4 面板「入选早于证据可得日」的成员推迟到合法日、产出 v5 面板的一次性修复（§12.71 前置） | 无——v5 已固化为 `build_moat_panel.py` 的基座 |
| `build_pit_attention_candidates.py`<br>`build_pit_attention_yearly.py`<br>`build_point_in_time_universe.py`<br>`pit_panel.py`<br>`build_judgment_input.py`<br>`analyze_survivorship_bias.py` | 2026-08-24 | 2026-11-24 | **时点关注度判定（OI-034/OI-040）全链工具**。判定轮 2026-08-12 完成、退市二遍盲判 08-21 完成，回测宇宙固化为 `panel_moat_bank_v6b.csv`（装配走 `build_moat_panel.py`）；中间产物在 `data/archive/pit-judgment-2026-08/`，协议在 `docs/archive/Ashare_pit_judgment_protocol.md`。重开判定按协议 §12，从这里取回工具 | `build_moat_panel.py`（面板装配唯一入口） |
| `analyze_research_expectation_signal.py` | 2026-08-24 | 2026-11-24 | 研报预期方向的前瞻收益检验（OI-034 第 8 步配套）。结论已沉淀，研报门槛未进任何现行规则 | 无；回测研究开关 `--research-gate` 仍在引擎 |
| `backtest_signal_replay.py` | 2026-08-24 | 2026-11-24 | 量价信号历史回放器。其对象（扫描器信号动物园）已于 v4.18（OI-063）整体删除，回放无信号可回放 | 无 |
| `report_backtest_yearly.py` | 2026-08-24 | 2026-11-24 | 按自然年拆解回测净值。逐年读数已由引擎汇总与 `scan_summaries.csv` 承载 | `backtest_valuation_strategy.py` 自带逐年输出 |
| `justified_multiple.py` | 2026-08-24 | 2026-11-24 | 合理倍数第二层（OI-023 沉淀件）。生产估值统一走 ROIC 引擎后无消费方 | `intrinsic_value.py` + `build_historical_valuation_bands.py` |
| `apply_quality_tier_column_backfill.py` | 2026-08-24 | 2026-11-24 | OI-024 的一次性回填（L1 `q2_moat_type`、L3 `tactical_thesis`，逐票常量表）。已执行；剩余三列按 §5.7 随季度复核逐票手工回填 | `backfill_quality_tier_columns.py`（六列建列与填充率自检，仍在用） |
| `build_overseas_dossiers.py`<br>`overseas_dossier_inputs.py` | 2026-08-24 | 2026-11-24 | 海外档案旧建带器（PEG／implied_pe／ddm3／justified_pb 等退役口径的硬编码输入表）。§6.8 已改 ROIC 口径由三表重算；**误跑会用退役口径覆盖 26 行海外估值表**；v4.111 起已无法 import（依赖的 `effective_valuation_tier` 随五档退役删除） | `fetch_overseas_statements.py` + `build_overseas_roic_bands.py`（§6.8） |
同类归档：`docs/archive/`（已完成的过程记录与已实施的方案设计）、
`data/archive/`（已跑完的工作队列与已结束轮次的产物）。
