# 归档：已退役的脚本

本目录保存用于历史复现的退役脚本；当前环境中的可运行性未作保证。现行入口读取工作流程。

判定标准（三条同时成立才归档）：①`docs/000_Ashare_workflow.md` 未引用；②无其他脚本 import；
③其产物已被现行产物取代或所属轮次已结束。

恢复时先检查依赖、仓库根路径与输入是否仍可重建，再迁回对应目录并运行检查。

**三个月规则（用户 2026-08-14 定）**：归档满三个月仍未被取回的，直接永久删除。
「可永久删除日」列即该日期，到期前请先确认表中「现行替代」一栏仍然成立。

| 脚本 | 归档日期 | 可永久删除日 | 退役理由 | 现行替代 |
| --- | --- | --- | --- | --- |
| `build_rejudge_dossiers.py` | 2026-09-19 | 2026-12-19 | §12.34 时点重判口径修复轮的档案生成器；该轮已结束，仓库内无任何引用 | 现行档案由 §6.5.2 逐票档案链生成 |
| `cutover_w0_baseline.sh` | 2026-09-19 | 2026-12-19 | OI-124 `W=0` 基准切换一次性脚本（含 `--rollback`），切换对象已成为基准 | `BASE` 常量（`sweep_backtest_configs.py`） |
| `make_w0_scan_configs.py` | 2026-09-19 | 2026-12-19 | OI-124 W=0 双线剂量扫描配置生成器，轮次已结案，无引用 | 新实验按 §9.3.1.2 手写相对 `BASE` 的配置 |
| `arms_vs_base_report.py` | 2026-09-19 | 2026-12-19 | 拼接多臂 14 起点行与生产 `BASE` 的一次性报表，无引用 | `sweep_backtest_configs.py --report` |
| `make_tier2d_configs.py` | 2026-09-19 | 2026-12-19 | §12.177 二维买卖档位扫描配置生成器，轮次已结案，无引用 | 同上 |
| `step_deltas.py` | 2026-09-19 | 2026-12-19 | §12.172 相邻臂逐起点配对 Δ 报表，轮次已结案，无引用 | `sweep_backtest_configs.py --report` 的配对读数 |
| `moat_audit_quant_evidence.py` | 2026-09-19 | 2026-12-19 | 2026-09-07 护城河审计轮的量化证据表生成器，无引用；同轮 `moat_audit_aggregate.py` 因数据记录引用仍留在实验目录 | 审计结论已落名单与分层表 |
| `fetch_hong_kong_universe.py`<br>`fetch_hong_kong_research_evidence.py`<br>`run_hong_kong_full_coverage_scoring.py`<br>`fetch_us_universe.py`<br>`fetch_us_research_evidence.py`<br>`run_us_full_coverage_scoring.py` | 2026-08-02 | 2026-11-02 | **港股/美股全覆盖打分管线整体退役**。其口径 `docs/moat-scoring-rubric.md` 自 2026-07-08（ADR-0006）起已被 A 股撤出，此后只服务这六个脚本；而海外覆盖已于 v1.22 改为 §6.8「海外关注清单」——只对**用户点名**的公司按 §5.7 分层、§6.5 定带，不做全市场打分。产物 `data/interim/{hong_kong,us}_*.csv` 停在 2026-05-14 | 工作流 §6.8 + `data/processed/overseas_watchlist_valuation.csv` + `scripts/overseas_quotes.py` |
| `build_a_share_full_rescan_queue.py` | 2026-08-02 | 2026-11-02 | 全市场第一轮三类初筛重扫的工作队列生成器。该轮已于 **2026-07-09 完成**（5,653 家：261 worth_attention / 5,332 boundary_pending / 60 garbage），队列不再需要重建 | 季度审查走 `build_quarterly_quality_review_queue.py`（§5.3）；全量重扫见 OI-036 |
| `fetch_a_share_research_evidence.py` | 2026-08-02 | 2026-11-02 | 早期研报证据抓取，产物 `a_share_research_queue.csv` 停在 2026-05-14（已删除），且其字段口径不含建带所需的一致预期覆盖机构数 | `fetch_a_share_valuation_evidence.py`（§6.3 一致预期覆盖机构数由它产出） |
| `apply_evidence_review.py` | 2026-08-02 | 2026-11-02 | 2026-08-01 分层证据复核轮的一次性回写工具，该轮已闭环（261 家全部 evidence-reviewed），复核记录见 `data/archive/completed-queues/evidence_review_log.md` | 无——后续分层变更走 §7.2 质量复核触发，逐票写入 |

| `build_pit_judgment_queue.py`<br>`fetch_delisted_financials.py` | 2026-08-14 | 2026-11-14 | **OI-040（幸存者偏差）配套的两个工具**。该轮已查实为**不可测的数据缺口**——本地行情与财务两侧均不含退市公司，九只已知退市股五项数据全缺，`data/raw/ohlcv` 的 5,210 个文件无一在 2026 年前终止。**队列造不出来、退市财务也补不齐**，两个脚本因而无对象可跑 | 无。OI-040 已于 2026-08-21 结案（回测日志 §12.106），协议在 `docs/archive/Ashare_pit_judgment_protocol.md` |
| `fetch_sina_original_financials.py` | 2026-08-14 | 2026-11-14 | 取原始披露口径财务以对冲东财的追溯重述污染。**该问题仍未验证**（登记在 §12.39 的效力边界里），但本脚本自 2026-08-11 起未再被任何口径调用 | 无现行替代。**若日后要查重述污染，从这里恢复**，不要重写 |
| `fetch_hk_annual_financials.py` | 2026-08-14 | 2026-11-14 | 港股逐年财务抓取。§6.8 海外关注清单只对**用户点名**的公司逐票定带，取数走 §6.8 三表重算，本脚本的全量年度指标无处消费 | `fetch_overseas_statements.py` + `build_overseas_roic_bands.py` + `overseas_quotes.py`（§6.8） |
| `cleanup_dossier_implied_growth_oi078.py` | 2026-08-21 | 2026-11-21 | **OI-078 的一次性回写工具**（v4.30 已执行）：把 `a_share_valuation_dossiers.csv` 的 `implied_growth_years` 178 份旧口径文本按句清理为只含手写可证伪命题；规则与人工核定项都在脚本里，清理前原文在 git 父提交 | 无——第八节首段此后由 `build_company_dossier_readmes.py` 机械生成，手写列不再承载带值 |
| `measure_pool_selection_bias.py` | 2026-08-14 | 2026-11-14 | 2010 年时点名单「进池 vs 未进池」此后收益的一次性度量，结论已写入 §12.25 并转为 OI-040 | 无——一次性度量，结论已沉淀 |
| `build_metric_states.py` | 2026-08-16 | 2026-11-16 | §12.61「每只股票只跟自己比」实验的指标层（pb／pe／pbroe 逐日状态，产物 `data/processed/metric_states/` 已随清理删除） | 无——§12.61 结论：自身分位无前瞻信息 |
| `fix_panel_entry_lookahead.py` | 2026-08-16 | 2026-11-16 | 把 v4 面板「入选早于证据可得日」的成员推迟到合法日、产出 v5 面板的一次性修复（§12.71 前置） | 无——v5 已固化为 `build_moat_panel.py` 的基座 |
| `build_pit_attention_candidates.py`<br>`build_pit_attention_yearly.py`<br>`build_point_in_time_universe.py`<br>`pit_panel.py`<br>`build_judgment_input.py`<br>`analyze_survivorship_bias.py` | 2026-08-24 | 2026-11-24 | **时点关注度判定（OI-034/OI-040）全链工具**。判定轮 2026-08-12 完成、退市二遍盲判 08-21 完成，回测宇宙固化为 `panel_moat_bank_v6b.csv`（装配走 `build_moat_panel.py`）；中间产物在 `data/archive/pit-judgment-2026-08/`，协议在 `docs/archive/Ashare_pit_judgment_protocol.md`。重开判定按协议 §12，从这里取回工具 | `build_moat_panel.py`（面板装配唯一入口） |
| `build_full_market_screen_queue.py`<br>`test_full_market_screen_queue.py` | 2026-09-05 | 2026-12-05 | OI-036 全市场重筛的取数与排队工具，该轮已于 2026-08-31 收口（v4.102），产物归 `data/archive/full_market_screen/` | 季度审查走 `build_quarterly_quality_review_queue.py`（§5.3） |
| `analyze_research_expectation_signal.py` | 2026-08-24 | 2026-11-24 | 研报预期方向的前瞻收益检验（OI-034 第 8 步配套）。结论已沉淀，研报门槛未进任何现行规则 | 无；回测研究开关 `--research-gate` 仍在引擎 |
| `backtest_signal_replay.py` | 2026-08-24 | 2026-11-24 | 量价信号历史回放器。其对象（扫描器信号动物园）已于 v4.18（OI-063）整体删除，回放无信号可回放 | 无 |
| `report_backtest_yearly.py` | 2026-08-24 | 2026-11-24 | 按自然年拆解回测净值。逐年读数已由引擎汇总与 `scan_summaries.csv` 承载 | `backtest_valuation_strategy.py` 自带逐年输出 |
| `justified_multiple.py` | 2026-08-24 | 2026-11-24 | 合理倍数第二层（OI-023 沉淀件）。生产估值统一走 ROIC 引擎后无消费方 | `intrinsic_value.py` + `build_historical_valuation_bands.py` |
| `apply_quality_tier_column_backfill.py` | 2026-08-24 | 2026-11-24 | OI-024 的一次性回填（L1 `q2_moat_type`、L3 `tactical_thesis`，逐票常量表）。已执行；剩余三列按 §5.7 随季度复核逐票手工回填 | `backfill_quality_tier_columns.py`（六列建列与填充率自检，仍在用） |
## 一次性作业脚本（`scripts/archive/slurm/`）

2026-09-19 归档、**2026-12-19 可永久删除**。这些 `sbatch` 是已结案课题（OI 编号或回测日志节号）的一次性提交包装：工作流程未引用、无脚本引用、结果已写入回测日志或 `docs/reports/`，正文可从 Git 取回。常设入口只剩 `scripts/slurm/` 下的 `daily_postclose.sbatch`、`rebuild_chain_with_fetch.sbatch`、`shadow_origin.sbatch`、`oi148_slippage.sbatch` 及仍被脚本引用的少数作业。重跑时按回测日志节号取回对应文件，先核对路径与输入是否仍可重建。

| 家族（件数） | 文件 |
| --- | --- |
| buy_fraction_*（2） | `buy_fraction_prepare_20260909.sbatch`, `buy_fraction_scan_20260909.sbatch` |
| buy_line_operating_*（2） | `buy_line_operating_prepare_20260909.sbatch`, `buy_line_operating_scan_20260909.sbatch` |
| c030r35_*（2） | `c030r35_adoption_20260910.sbatch`, `c030r35_land_20260910.sbatch` |
| ebds03_*（2） | `ebds03_clause4_20260910.sbatch`, `ebds03_land_20260910.sbatch` |
| equity_bond_*（4） | `equity_bond_high_base_20260909.sbatch`, `equity_bond_opt_20260910.sbatch`, `equity_bond_opt_refine_20260910.sbatch`, `equity_bond_scan_20260909.sbatch` |
| ex_winner_*（1） | `ex_winner_symmetry.sbatch` |
| exec_timing_*（1） | `exec_timing_sweep.sbatch` |
| exwinner_*（2） | `exwinner_2011_diag.sbatch`, `exwinner_rel_rerun.sbatch` |
| ladder_*（2） | `ladder2_sweep.sbatch`, `ladder_pairswap_sweep.sbatch` |
| ma_slope_*（2） | `ma_slope_20260914.sbatch`, `ma_slope_smoke_20260914.sbatch` |
| maintenance_cash_*（2） | `maintenance_cash_build_20260909.sbatch`, `maintenance_cash_scan_20260909.sbatch` |
| oi110_*（1） | `oi110_sellline.sbatch` |
| oi113_*（1） | `oi113_addon_gate.sbatch` |
| oi114_*（5） | `oi114_adopt_checks.sbatch`, `oi114_adopt_checks_m19.sbatch`, `oi114_margin_fine.sbatch`, `oi114_side_unify.sbatch`, `oi114_swap_margin.sbatch` |
| oi115_*（1） | `oi115_window_step.sbatch` |
| oi120_*（1） | `oi120_cooldown_split.sbatch` |
| oi122_*（1） | `oi122_dose_curves.sbatch` |
| oi123_*（1） | `oi123_resweep14.sbatch` |
| oi124_*（2） | `oi124_rebase_m018.sbatch`, `oi124_w0_line_scans.sbatch` |
| oi128_*（4） | `oi128_margin_dose.sbatch`, `oi128_minority_ab.sbatch`, `oi128_minority_sweep.sbatch`, `oi128_signal_layer.sbatch` |
| oi128_130_*（2） | `oi128_130_build_ab.sbatch`, `oi128_130_land.sbatch` |
| oi131_*（4） | `oi131_exright_ab.sbatch`, `oi131_land.sbatch`, `oi131_prereq.sbatch`, `oi131_tierfwd_base.sbatch` |
| oi132_*（2） | `oi132_land_a.sbatch`, `oi132_land_b.sbatch` |
| oi135_*（4） | `oi135_decomp_anchor.sbatch`, `oi135_gate_trend.sbatch`, `oi135_troughoff_diag.sbatch`, `oi135_why_diag.sbatch` |
| oi136_137_*（4） | `oi136_137_dose.sbatch`, `oi136_137_land.sbatch`, `oi136_137_margin.sbatch`, `oi136_137_signal.sbatch` |
| oi138_*（1） | `oi138_c11_stage1.sbatch` |
| oi140_*（1） | `oi140_combo_c1.sbatch` |
| oi142_*（1） | `oi142_land.sbatch` |
| oi148_*（1） | `oi148_slippage_apass.sbatch` |
| oi150_*（2） | `oi150_complete.sbatch`, `oi150_overseas_forward.sbatch` |
| oi157_*（2） | `oi157_t1gain_signal.sbatch`, `oi157_t1gain_sweeps.sbatch` |
| oi165_*（1） | `oi165_panel_guard.sbatch` |
| oi167_*（1） | `oi167_land_20260913.sbatch` |
| oi168_*（3） | `oi168_wc_attribution_20260909.sbatch`, `oi168_wc_build_20260909.sbatch`, `oi168_wc_scan_20260909.sbatch` |
| oi174_*（1） | `oi174_requal_20260913.sbatch` |
| oi179_*（4） | `oi179_20260914.sbatch`, `oi179_costs_20260914.sbatch`, `oi179_signals_20260914.sbatch`, `oi179_smoke_20260914.sbatch` |
| oi180_189_*（1） | `oi180_189_20260914.sbatch` |
| oi186_*（1） | `oi186_cooldown_20260914.sbatch` |
| position_cap_*（3） | `position_cap_25_20260908.sbatch`, `position_cap_25_strict_20260908.sbatch`, `position_cap_high_20260908.sbatch` |
| reaudit_minority_*（6） | `reaudit_minority_attrib.sbatch`, `reaudit_minority_fine.sbatch`, `reaudit_minority_followup.sbatch`, `reaudit_minority_gain.sbatch`, `reaudit_minority_rejected.sbatch`, `reaudit_minority_rules.sbatch` |
| rebuild_*（6） | `rebuild_chain_step3.sbatch`, `rebuild_oi126_002128.sbatch`, `rebuild_oi126_probe.sbatch`, `rebuild_valuation_chain.sbatch`, `rebuild_w0_display.sbatch`, `rebuild_w0_production.sbatch` |
| residual_clear_*（2） | `residual_clear_anchors.sbatch`, `residual_clear_sweep.sbatch` |
| residual_cny_*（3） | `residual_cny_anchors.sbatch`, `residual_cny_final.sbatch`, `residual_cny_sweep.sbatch` |
| sb1_*（4） | `sb1_daily_buys.sbatch`, `sb1_daily_buys_checks.sbatch`, `sb1_land.sbatch`, `sb1_platform_sweep.sbatch` |
| selection_edge_*（1） | `selection_edge_baseline.sbatch` |
| shadow__*（1） | `shadow_portfolio.sbatch` |
| swap__*（3） | `swap_control_tolerances.sbatch`, `swap_repeat_candidate_20260917.sbatch`, `swap_variants_sweep.sbatch` |
| t1_info_*（2） | `t1_info_exwinner_u.sbatch`, `t1_info_sweep.sbatch` |
| tier2d_*（1） | `tier2d_sweep.sbatch` |
| trough_guard_*（2） | `trough_guard_checks.sbatch`, `trough_guard_review.sbatch` |
| us_sp100_*（1） | `us_sp100_panel.sbatch` |
| us_sp500_*（8） | `us_sp500_a_nocredit.sbatch`, `us_sp500_a_nocredit9.sbatch`, `us_sp500_align.sbatch`, `us_sp500_data.sbatch`, `us_sp500_panel.sbatch`, `us_sp500_states.sbatch`, `us_sp500_sweep.sbatch`, `us_sp500_tierfwd.sbatch` |
| volume_trigger_*（2） | `volume_trigger_stage1.sbatch`, `volume_trigger_uset.sbatch` |
| whipsaw_*（7） | `whipsaw_joint.sbatch`, `whipsaw_joint_census.sbatch`, `whipsaw_joint_signal_audit.sbatch`, `whipsaw_joint_validate.sbatch`, `whipsaw_swap_diag.sbatch`, `whipsaw_swap_r1.sbatch`, `whipsaw_swap_sweep.sbatch` |
| 其他单件（14） | `buyline_swapdir_sweep.sbatch`, `corr_filter_arm.sbatch`, `drawdown_review_20260911.sbatch`, `m3_rereg_20260910.sbatch`, `metric_m2_reregister.sbatch`, `open_issue_dose.sbatch`, `panel_tier_forward_baseline.sbatch`, `pv_episode_20260914.sbatch`, `rank_episode_20260914.sbatch`, `risk_budget_20260911.sbatch`, `rolling_metric_audit_20260909.sbatch`, `startset14_reregister.sbatch`, `stop_max_20260916.sbatch`, `watchlist_restore_20260907.sbatch` |

同类归档：`docs/archive/`（已完成的过程记录与已实施的方案设计）、
`data/archive/`（已跑完的工作队列与已结束轮次的产物）。
