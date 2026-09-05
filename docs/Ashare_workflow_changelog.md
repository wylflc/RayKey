# A股工作流版本记录（docs/000_Ashare_workflow.md）

自 v1.00 起版本记录移至本文件维护，工作流正文只保留指针。编号沿革：v1-v31 为初期整数系列，v0.31 起切换 v0.x 格式，v1.00 为四袖架构定版。

每行只写规则变化与落点（章节、文件、常量），依据只给回测日志节号；不写用户原话、读数与过程。v4.65 以前的行在 `docs/archive/Ashare_workflow_changelog_v1.00-v4.65.md`；本表 2026-09-05 精简前的原文用 `git show 0f67c53c:docs/Ashare_workflow_changelog.md` 取回。

| 版本 | 日期 | 内容 |
| --- | --- | --- |
| v4.144 | 2026-09-05 | 回测扫描台账拆分：`data/backtest/scan_summaries.csv` 只留现行计量口径行，旧口径行移入 `data/archive/scan_summaries_m1.csv`；新增按臂索引 `data/backtest/scan_arms_index.csv`（归并后自动重建），§12.1 第 12 款改按它数臂。落点：`clean_derived_artifacts.py`、`start_sign_correlation.py`、README、CLAUDE.md |
| v4.143 | 2026-09-05 | 仓库整理：`data/processed/experiments`→`data/experiments`、`data/processed/backtest`→`data/backtest`、两份 000_ 阅读文件移入 `docs/`、评审报告归 `docs/reports/`、OI-036 产物与 `financials_original`／`a_share_company_profiles.csv` 归 `data/archive/`；决策日志核心池改「汇总行＋变化行」（§2）并归档旧纪元行；每日扫描日志按月归档（§9.1 第 6 步）；回测日志每节 ≤1.5 KB、changelog 每行只写规则与落点（§12.1 第 9 款），两者旧纪元移入 `docs/archive/`；open issues 已结案索引拆到 `Ashare_workflow_open_issues_closed.md`。落点：`build_a_share_core_valuation_pool.py`、`build_a_share_company_analysis_index.py`、`clean_derived_artifacts.py`、`.gitignore`、CLAUDE.md、README |
| v4.142 | 2026-09-05 | 计量口径 m2：全期 CAGR 按首末净值日日历年数；Sharpe 全期与滚动共用逐日超额简单收益均值 ÷ 样本标准差 × √244，rf 按期首可得最新观测、缺覆盖计 0 并报 `rf覆盖率`；summary 与扫描输出带 `计量版本`、`--report` 不跨版本配对；新增跨起点尾部与强平缓冲；报表首页只留决策读数／采纳判定／跨起点尾部。§10.3 策略收益改单位净值链乘（`strategy_return_tracker.py`，快照加 4 列）。落点：§12.1 第 2 款、§10.3、`backtest_valuation_strategy.py`、`sweep_backtest_configs.py`、`dose_table.py`、在册读数重登。OI-146／147 结案，登记 OI-148~151。依据 §12.192 |
| v4.141 | 2026-09-03 | 海外三表补东财数据中心两条补缺源：港股缺已付股息按 `RPT_HKF10_INFO_DIVIDEND` 分红事件折算；维护行缺归母净利／综合收益／已付股息按 `RPT_USF10_FN_INCOME`／`RPT_USF10_INFO_DIVIDEND` 补入。落点：`fetch_overseas_statements.py`、§6.8 维护行句。依据 §12.187 |
| v4.140 | 2026-09-03 | 海外引擎移植 §6.5.2.3 股本口径：年报间外生权益识别、经营账面 E_op、季报观察点 x；三表映射补归母净利与综合收益（`net_income`／`tci`／`net_income_ytd`／`dividends_paid_ytd`）。落点：`build_overseas_roic_bands.py`、`fetch_overseas_statements.py`、`overseas_statement_overrides.csv` 四列、§6.8 锚句。OI-144 结案。依据 §12.186 |
| v4.139 | 2026-09-03 | 海外引擎统一到 A 股口径：锚改 NOPAT/母公司权益 × 当期 BPS、季报当期按 TTM 因子、λ 与中位只取年报、`TRAIL_WEIGHT` 0、守卫比率不回加回购。落点：`build_overseas_roic_bands.py`、§6.8。OI-143 结案。依据 §12.185 |
| v4.138 | 2026-09-03 | 海外引擎补周期守卫坡道（`PEAK_RAMP = 0.3`）、增长态信任度 λ、谷底守卫、增速腿 ×(1−w)×d；三表取数补现金换签（`DebtSecuritiesCurrent`）与时点补缺。落点：`build_overseas_roic_bands.py`、`fetch_overseas_statements.py`、§6.8。登记 OI-143。依据 §12.184 |
| v4.137 | 2026-09-03 | 回退到 v4.134：换仓接收方守卫关。落点：`SEC93_SWAP_SOURCE_BLOCK = -1.0`、`BASE --swap-source-block -1`、§9.3.1 换仓行、§9.3.2 第 5 步、在册读数、两个测试。保留第 4 款放宽、相对贡献尺与引擎开关。依据 §12.182／§12.183 |
| v4.136 | 2026-09-03 | 去赢家赢家尺改为「盈亏 ÷ 前一日净资产」累计贡献：`Lot.contrib`、trades `contrib` 列、summary `前五赢家贡献`。落点：§12.1 第 3／11 款、`backtest_valuation_strategy.py`、`ex_winner_dose.py`、`delta_attribution.py`、去赢家在册读数。依据 §12.182 |
| v4.135 | 2026-09-03 | 换仓接收方守卫 K=1 采纳；§12.1 第 4 款放宽为「各项 ≥ −0.15pp，或至多一项落在 [−1pp, −0.15pp)」。落点：`SEC93_SWAP_SOURCE_BLOCK = 1.0`、`BASE --swap-source-block 1`、§9.3.1 换仓行、§9.3.2 第 5 步、在册读数。依据 §12.179／§12.181 |
| v4.134 | 2026-09-03 | OI-142 结案：同一持仓每日合计至多减一档，当日已涨幅减持的持仓不作换仓卖出源。落点：引擎 `--swap-gain-once` 入 `BASE`、扫描器 `trimmed_today`、§9.3.1 换仓行、§9.3.2 第 4 步、在册读数。依据 §12.180 |
| v4.133 | 2026-09-02 | 换仓边际 0.16 → 0.15。落点：`SEC93_SWAP_MARGIN`、`check_swap_margin_scale_drift.MARGIN`、`BASE`、§9.3.1、在册读数。依据 §12.176 |
| v4.132 | 2026-09-02 | OI-136／137 结案：相关性上限取消（只计算列报告、不过滤）、涨幅减持改 ≥110% 不看走势、涨幅源作换仓源不要求弱势、换仓边际 0.18 → 0.16。落点：`SEC93_MAX_CORR 1.0`／`SEC93_GAIN_SELL 1.10`／`SEC93_SWAP_MARGIN 0.16`、`holding_trim_signal`、`BASE`、§9.3.1／§9.3.2 第 3~5 步／§9.2、备用清单。依据 §12.174／§12.175 |
| v4.131 | 2026-09-02 | OI-134 结案：扫描器负 `--funds` 透传（卖出款先补缺口、余额才买入）。落点：`screen_daily_volume_price_signals.py`、§10.2、`test_daily_execution_plan.py` |
| v4.130 | 2026-09-02 | OI-132 结案：购买法收购当年分子按并表月数年化，手工登记表 `data/reference/consolidation_events.csv`。落点：§6.5.2.4、`roic_inputs.py`、`test_consolidation_annualize.py`、买入线 1.0453 → 1.0454。依据 §12.170 |
| v4.129 | 2026-09-02 | OI-118／119／120／121 结案：冷却计数器买卖分侧（`sell_counters`、`daily_cooldown_state.csv` `side` 列、回测缺省分侧）；§12.1 第 2 款删正号起点数、第 4 款「不劣」改 Δ ≥ −0.15pp；主读数与复利读数两表各取一份的采纳规则；§10 改题。落点：§9.3.3、§12.1、扫描器、`sweep_backtest_configs.py`【采纳判定】表。依据 §12.168／§12.169 |
| v4.128 | 2026-09-02 | OI-133 结案：港股有息负债补映射租赁负债、应付债券、可转换票据。落点：`fetch_overseas_statements.py` `HK_ITEMS`／`HK_DEBT_KEYS`、§6.8 重算 |
| v4.127 | 2026-09-02 | 海外点名建档成文（§0 路由行、§6.8 六步程序、阅读版附表列全清单、档案目录登记不变量 `dossier_registration_gaps.csv`）。OI-128／129／130 结案：少数股东扣减改 `max(账面, m × (EV − fin_nd))`；重述版本化 `restatement_archive.py` 与按可得日选版本；§6.7 第 5.5 步检查⑦股本事件复核＋`share_event_reviews.csv`、`entity_reset_dates.csv` 加 `known_from`；买入线 1.0138 → 1.0453。落点：`roic_inputs.py`、建带器、`apply_forecast_band_overlay.py`、`build_overseas_roic_bands.py`、§6.5.2.4／§6.7、在册读数。依据 §12.167 |
| v4.126 | 2026-09-02 | OI-131 结案：银行/保险股利折现覆盖按除权参考价折算。落点：`rebuild_bank_bands.py`、扫描器 `bank_dividend_intrinsic`、买入线 0.9976 → 1.0138、在册读数。依据 §12.166 |
| v4.125 | 2026-09-02 | OI-127：三大报表覆盖缺口不再静默退回权益口径——写 `statement_coverage_gaps.csv`／`valuation_statement_gaps.csv` 并非零退出，命中池内代码判 blocking。落点：取数脚本、建带器、校验步、§6.7 第 1／2 步 |
| v4.124 | 2026-09-02 | OI-125／126 结案：三大报表取数增追溯重述探针（每次重取资产负债表比 `UPDATE_DATE`，变则整只重取，`--no-probe` 关闭；实变写 `statement_restatements.csv`）；§6.7 第 5.5 步增检查⑥重述年报股本基。落点：`fetch_a_share_financial_statements.py`、`audit_financial_panel_consistency.py`、`financials_corrections.csv`（中国神华 FY2025 bps） |
| v4.123 | 2026-09-01 | 新增 `fetch_a_share_share_changes.py` → `data/raw/share_changes/a_share_share_changes.csv`（股本变动事件表）；定点修复电投能源 FY2025 权益重述与 bps 订正。落点：§6.7 第 1 步、`financials_corrections.csv`。登记 OI-126 |
| v4.122 | 2026-09-01 | §6.7 第 5.5 步增检查⑤实时股本对照（池内 `total_market_cap_bn ÷ valuation_price` 对面板 `归母÷EPS`，偏差 >5% 报可疑，不闸建带）。落点：`audit_financial_panel_consistency.py`。补记 OI-125 |
| v4.121 | 2026-09-01 | 修 §6.7 第 5.5 步 ROE 自洽核对口径选择键单位错配（两侧同为百分数、按对数距离取）。落点：`audit_financial_panel_consistency.py`。登记 OI-125 |
| v4.120 | 2026-09-01 | 换仓边际 0.19 → 0.18。落点：`SEC93_SWAP_MARGIN`、`BASE`、§9.3.1、`check_swap_margin_scale_drift.MARGIN`、测试、在册读数（W=0 双口径）。依据 §12.164 |
| v4.119 | 2026-09-01 | `W=0`（`--roic-trail-weight 0`）换为生产基准；换手降为参考项、第 4 款不计入；买入线 0.9343 → 0.9976；单票上限 0.60 与授信 0.666 维持。落点：§6.7 第 2／2b 步、§9.3.1、§12.1、`SEC93_BUY_LINE`、`BASE`、`align_buy_line.py` 面板缺省改 v6b、`.gitignore` 暂存规则。依据 §12.163 |
| v4.118 | 2026-09-01 | §12.1 第 2 款写入标准指标集（两口径各一份，每项报水平＋配对差中位＋变好起点数）；第 3 款剔除集 A／U；新增第 4 款「去赢家全面优秀」与三项采纳前置，原第 4~11 款顺延。落点：`sweep_backtest_configs.py` `STANDARD_SET`、`ex_winner_symmetry.py`、在册读数双口径。登记 OI-124。依据 §12.162 |
| v4.117 | 2026-09-01 | 标准起点集改为路径 ≥10 年的 14 个半年档起点（含扩集规则），符号数分母 x/14。落点：§12.1、`sweep_backtest_configs.DEFAULT_STARTS`、在册读数重登。依据 §12.160 |
| v4.116 | 2026-09-01 | OI-122 结案：臂间比较与未来年化表述基准为复利读数、对照表按 Δ年化 排序；水平引用只用全期口径；互不重叠 5 年块中位必报。落点：§12.1 第 2 款、引擎 summary 新增两键、`sweep_backtest_configs.py` `PRIMARY_KEY`／FIELDS。依据 §12.157 |
| v4.115 | 2026-09-01 | 全期年化升为第五项决策读数（复利读数），任一为负即不采纳；轨道 A 护栏改「主读数与复利读数各自损失 ≤1pp」。落点：§12.1 第 2 款、`sweep_backtest_configs.DELTA_KEYS`、测试 |
| v4.114 | 2026-09-01 | OI-114 结案：接受混标度判据，§6.7 增第 7 步换仓边际标度漂移守卫 `check_swap_margin_scale_drift.py`（g 均值在册 0.0164、容差 ±0.01）。依据 §12.153 |
| v4.113 | 2026-09-01 | 长跑年化（2009-11／2011-11 锚点全期 CAGR）入 §12.1 第 2 款必报读数；换仓边际 0.20 → 0.19。落点：`sweep_backtest_configs.py` `LONGRUN_STARTS`、`SEC93_SWAP_MARGIN`、`BASE`、在册读数。依据 §12.152 |
| v4.112 | 2026-09-01 | 换仓边际 0.1437 → 0.20；§12.1 对齐口径改为「边际按 0.01 一档剂量扫描重定、不随买入线缩放」；在册观测订正 508,154／17.777%。落点：§9.3.1、`SEC93_SWAP_MARGIN`、`BASE`、测试。依据 §12.149~§12.151 |
| v4.111 | 2026-08-31 | OI-112 结案：退役五档展示体系，`valuation_tier` 整列删除，反推禁令上移 §1；「无法估值」改按带为空判。落点：§6.2 删、§9.2／§11.3／§6.7／§6.8 文案、`build_a_share_core_valuation_pool.py`、扫描器、跟踪器、索引、`validate_valuation_bands.py`、档位快照文件与参数删除 |
| v4.110 | 2026-08-31 | OI-116／117 结案（纯文档）：§9.3.1「止盈」行改「只有涨幅减持一条」；§12.1 第 2 款补「四项一律取全样本表」。落点：`test_strategy_parameter_sync.py` 三条断言 |
| v4.109 | 2026-08-31 | OI-110 结案：删除 §9.3.1 估值减持行，三线变两线（买入线 0.9343／换仓边际 0.1437）；OI-111：平均仓位改 `持仓市值 ÷ 净资产`，集中度六列入报表；修 `clean_derived_artifacts.py` 归并覆写台账缺陷。落点：`SEC93_SELL_LINE`／`SELL_LINE` 删除、`BASE` 去 `--sell-line`、`sweep_backtest_configs.py` FIELDS。依据 §12.146／§12.147 |
| v4.108 | 2026-08-31 | §12.1 第 3 款删「去赢家读数不单独作采纳依据」。依据 §12.145 |
| v4.107 | 2026-08-31 | §12.1 第 3 款删「两表同号」否决，两表反号改按发现报告。依据 §12.145 |
| v4.106 | 2026-08-31 | §12.1 第 9 款：换仓方向性一表须同报 `swap_regime_control.py` 四表对照；正文第 1 行补记 v4.106。依据 §12.144 |
| v4.105 | 2026-08-31 | §12.1 扩为三层评价：两条采纳轨道（A 机制修复／B 收益动机）、两表同号、信号层三表（`selection_edge_audit.py`、`panel_tier_forward.py`）、Δ 归因集中度（`delta_attribution.py`）、搜索台账。落点：§12.1 第 1／3／9~11 款。依据 §12.143 |
| v4.104-a | 2026-08-31 | 迁移至 Snellius：19 个脚本绝对路径改按 `__file__` 解析；`test_failure_semantics.py` 取数桩修正；CLAUDE.md 机器约束改 SLURM 口径 |
| v4.104 | 2026-08-31 | §9.3.2 新增第 6 步同日对冲（同票当日买卖按较小者抵消，出名单与止损不抵消）。落点：`BASE --net-same-day`、扫描器计划层、在册读数重登；OI-107／109 结案，OI-108 不修订。依据 §12.141／§12.142 |
| v4.103 | 2026-08-31 | OI-106 处置：逐季面板 `--refresh` 回访已在库报告期吸收追溯重述；`fetch_a_share_quarterly_financials.py` 加 `keep_precision` 防低精度覆盖（`test_fetch_quarterly_precision.py`）；阅读版无法估值行三列改取模型最近评估期（`model_evaluated_report_date`） |
| v4.102 | 2026-08-31 | OI-036 与 OI-104 结案：复核队列按 08-31 重建，作业档归 `data/archive/model-blind-trial-2026-08-30/`；SPA 验证通过、B2 全量替换不采纳，生产不改。依据 §12.140 |
| v4.101 | 2026-08-30 | 全市场重筛队列两项守卫：`screen_queue.csv` 加 `prior_queue_tier`／`tier_move`（机械导出越线）、`scope_check`（毛利率同比跳变 ≥8pp 且营收同比 ≥+50%）。落点：`build_full_market_screen_queue.py`（现归 `scripts/archive/`）与其测试 |
| v4.100 | 2026-08-30 | 排队层三条判据改 TTM 口径（`tier_inputs` 兜底链、`ytd_consistent` 守卫，队列加 `tier_basis` 等四列）；251 家 C 层改判为 claude-opus-5 复判并补双盲第三轮（类别 251/251 一致，材料在 `data/archive/model-blind-trial-2026-08-30/`）。落点：`build_full_market_screen_queue.py` |
| v4.99 | 2026-08-30 | 删除 §10.1 第 3 条 20 日均成交额 5,000 万门槛（回测从未实现，生产收敛到基准）。落点：扫描器 `MIN_AMOUNT_MA20`／`liquid_ok` 删除、§3／§8.3／§9.3.1／§9.3.2 第 1 步。五粮液 L1 → L2 |
| v4.98 | 2026-08-30 | 7 家升入 `worth_attention`（核心池 207 → 214）、2 家改档；`apply_valuation_band_cards.py` 加 `seed_new_pool_rows`；OI-036 三项预筛缺陷落为 `screen_queue.csv` 常驻列与 `classify()` 规则；新增 `test_full_market_screen_queue.py` |
| v4.97 | 2026-08-30 | OI-036 中报窗收口：`verdicts.csv` 落到 `basis=2026H1`，三类表刷新证据日；`build_full_market_screen_queue.py` 名录补漏只打印不入队；`fetch_a_share_universe.py` 加 `pick_clean_name`（交易状态前缀不进简称） |
| v4.96 | 2026-08-30 | §5.3 名单刷新剔除已终止上市代码（146 只），三类表与 OI-036 队列同步移出；新增 `test_fetch_a_share_universe.py` |
| v4.95 | 2026-08-28 | §12.1 第 3 款：每轮扫描同时出统一剔除 BASE 前五大赢家的第二张表（`sweep_backtest_configs.py` 缺省自动跑、`--no-ex-top5` 关闭）；引擎 summary 加前五赢家三列；研究开关 `--sell-confirm`／`--sell-tol`／`--stop-tol`。依据 §12.138 |
| v4.94 | 2026-08-28 | §10.2 订正 `--funds` = 券商可用保证金 + 现金；新增 §10.3 策略收益跟踪（基准净资产 2,811,530.99，快照加三列，峰值与回撤按策略期计） |
| v4.93 | 2026-08-28 | §10.2 可用资金改以券商可用保证金为准，比例式退为未回报时估算；个人体系 §4 与 §2 账户快照行同步 |
| v4.92 | 2026-08-28 | 采纳 SPA：候选侧读生产带、持仓侧读逐票取候选侧与 B2 较高 V 的持仓侧带；减持线 2.4671 → 2.4257。落点：§6.7 第 2b／3／4 步（`build_hold_daily_states.py`、`build_hold_model_bands.py`）、§2 持仓侧带真值、扫描器 `--hold-bands`、跟踪器、回测 `--hold-states` 入 `BASE`、在册读数。依据 §12.136／§12.137 |
| v4.91 | 2026-08-28 | §6.5.2.4 改为主体重置：`entity_reset_dates.csv`，建带器 `--entity-reset-file`；手工带机制退役 |
| v4.90 | 2026-08-26 | 日报时点入口收口：`a_share_signal_dates.py`，§6.7 全链与 §7.1 队列只接受 `--signal-date`，扫描器删 `--evidence-date` |
| v4.89 | 2026-08-26 | OI-105 结案：实时价格触发 2% 确认全部不采纳；§6.1 与阅读版新增 L4 归档区。依据 §12.135 |
| v4.88 | 2026-08-25 | OI-104 替代方案 A/B：建带研究开关 `--trough-ratchet`、`--ttm-trust`、`--ttm-trust-delta`、`--trough-lift`，`--codes-file` 范围建带快链；全部不采纳，B2 作影子候选；`quarterly_anchor_response_audit.py` 入库。依据 §12.134 |
| v4.87 | 2026-08-25 | OI-103 结案：§6.5.1 每股锚「其后现金分红」改按期末权益是否已扣判（`dividends_booked_since`）。落点：建带器、`test_equity_anchor.py` 14 例、在册读数。依据 §12.133 |
| v4.86 | 2026-08-25 | 补正 OI-102：拼多多证据推进至 2026Q2；过期预期日只在正式证据推进后清理；核心池阅读版删版本迭代与方法说明 |
| v4.85 | 2026-08-25 | OI-102 结案：新增 `overseas_report_evidence.csv`；`fetch_overseas_statements.py` 改季报合成 TTM，`overseas_statement_overrides.csv` 官方报表覆盖；年度 `notice_date` 改实际 filed 日；新增 `test_overseas_report_evidence.py` |
| v4.84 | 2026-08-25 | OI-100 结案：新浪配股表全量 5,116 只取齐，§6.7 第 2-3 步重建；三线、生产带与在册读数不重登 |
| v4.83 | 2026-08-25 | OI-101 结案：§9.3.1 换仓行与 §9.3.2 第 4／5 步写明只由未持仓候选触发、卖出款按 P/V 升序不定向；代码不动，`--swap-held-trigger`／`--swap-proceeds target` 留研究开关。依据 §12.129~§12.132 |
| v4.82 | 2026-08-25 | `build_pool_model_bands.py` 生产带加 `model_evaluated_at`，估值复核日取 max(采纳带可得日, `model_evaluated_at`)（§7.3 成文）；宏桥控股／广东宏大／奥特维中报复核；§11.5 回写 08-24 三笔成交 |
| v4.81 | 2026-08-25 | OI-100 前两步：优先集配股表取齐；建带器 `split_factor` 与 EPS 重述候选不计配股；§6.7 第 2-6 步重跑；在册读数重登为新 `BASE`。依据 §12.128 |
| v4.80 | 2026-08-24 | 审计批 C＋D：回测 `--fill-missing skip`、`--dividend-tax`、配股事件（`fetch_ohlcv_history.py` 新浪配股表、事件库加 `rights_ratio`／`rights_price`）、`--swap-repeat skip` 入 `BASE`；§11.4 落地 `apply_holdings_corporate_action.py` 与台账 `holdings_corporate_actions_applied.csv`；§9.3.1.2 补回测执行与公司行动口径；新增 `test_corporate_actions_tax.py`、`test_apply_holdings_corporate_action.py`。依据 §12.128 |
| v4.79 | 2026-08-24 | 审计批 B：扫描器 `section93_execution_plan` 按 §9.3.2 先卖后买生成完整执行清单（止损复核、出名单、减持、换仓、余仓清空），新产物 `daily_sell_plan.csv`；§9.3.3 比例冷却计数器落地 `daily_cooldown_state.csv`；跟踪器加 `ma20`／`ma60`／`stop_line`；新增 `test_daily_execution_plan.py`。落点：§2／§8.2／§9.1／§9.3.3／§11.3 |
| v4.78 | 2026-08-24 | 审计批 A：`build_report_update_queue.py` 三族只取公告日 ≤ `--as-of` 的行（`test_report_update_queue.py`）；个人体系 v1.29 对齐工作流（删数量目标、PE 判据、清算价值地板与股东回报上限两节）；`CONTEXT.md`／ADR-0005 修正；分层表证据字段回填；三类表补 48 只新股；`verdicts.csv` 加 `judged_by_model`／`workflow_version`／`rubric_sha256` |
| v4.77 | 2026-08-24 | OI-099 结案：银行/保险股利折现分子改「最近已知完整财年分红、自预案公告日计入」，唯一实现 `divspread_dividend.py`；除权事件加 `plan_notice_date`／`progress`；`rebuild_bank_bands.py` 同步写 `valuation_label`；`is_bank_name` 改名单判；新增 `test_divspread_dividend.py`；在册读数重登，三线不动。依据 §12.127 |
| v4.76 | 2026-08-24 | OI-098 结案：`fetch_a_share_financial_statements.py` 增量规则改按 `--as-of` 判应到年报期重取；北交所后缀改 `.BJ`；新增 `test_statement_refresh.py`；§6.7 第 1 步命令加 `--as-of` |
| v4.75 | 2026-08-24 | OI-024 结案：分层表六个研究字段全池初稿回填（不改档位与分数） |
| v4.74 | 2026-08-24 | OI-097：`fetch_cost_of_equity_inputs.py` 并入 §6.7 第 1 步；OI-096：扫描决策日志只记结论行（`data_error`／`insufficient_price_history`／`review_frozen`），`detect_last_scan` 改读上一份 `daily_buy_candidates.csv`，历史 `daily_signal_state` 行清除 |
| v4.73 | 2026-08-24 | OI-095 结案：跟踪器取数改经扫描器 `fetch_daily_rows` 同一实现；生产带按 as-of 载入（`pv_ratio.load_model_bands` 加 `as_of`）；§8.3／§11.3 成文 |
| v4.72 | 2026-08-24 | OI-094 结案：§5／§7 队列财务判据改读 `data/raw/financials/` 逐季面板（新增 `quarterly_panel_indicators.py`）；删除 `a_share_financial_indicators.csv`；§5.6 删「负债、研发」判据 |
| v4.71 | 2026-08-24 | OI-093 结案：扫描器相关性改用当日已取的前复权 K 线（`CLOSE_SERIES`），重叠不足 120 根返回未知并在报告列名单；§9.3.1 相关性行补数据源与阈值 |
| v4.70 | 2026-08-24 | 建仓止损锚恒为成交日 MA60，取不到时退 MA20（§9.3.5）；`BASE --entry-below-ma60 ma60_stop`；在册读数重登。依据 §12.126 |
| v4.69 | 2026-08-24 | 取消 §9.3.1 走势行的建仓放弃规则；`BASE --entry-below-ma60 ma20_stop`；在册读数重登。依据 §12.126 |
| v4.68 | 2026-08-24 | OI-092 结案：§9.3 三处成文改从实现（走势行、止损行、§9.3.2 第 4 步余仓清空）；三口径留研究开关并显式入 `BASE`；`--until` 缺省跑满状态文件。依据 §12.126 |
| v4.67 | 2026-08-24 | 删除「券商实际授信 190 万」残留，授信唯一为 0.666 × 当日净资产；§2 台账行改「账户快照」，退役 `credit_line_cny` 列；个人体系 §4 同步 |
| v4.66 | 2026-08-24 | 融资授信改比例口径：授信 = 当日净资产 × 66.6%、不设金额上限。落点：§10.2、§2、个人体系 §4、`BASE --credit-ratio 0.666`、测试、在册读数重登。依据旧纪元日志 §12.125 |
