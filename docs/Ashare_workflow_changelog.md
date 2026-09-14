# A股工作流版本记录（docs/000_Ashare_workflow.md）

自 v1.00 起版本记录移至本文件维护，工作流正文只保留指针。编号沿革：v1-v31 为初期整数系列，v0.31 起切换 v0.x 格式，v1.00 为四袖架构定版。

每行只写规则变化与落点（章节、文件、常量），依据只给回测日志节号；不写用户原话、读数与过程。v4.65 以前的行在 `docs/archive/Ashare_workflow_changelog_v1.00-v4.65.md`；本表 2026-09-05 精简前的原文用 `git show 0f67c53c:docs/Ashare_workflow_changelog.md` 取回。

| 版本 | 日期 | 内容 |
| --- | --- | --- |
| v4.187 | 2026-09-14 | OI-180—189：修复信号档位、报价基准、必需输入、整批发布、名单与来源去重、持仓标价、模型拒绝传播及生成顺序；成交后冷却规则保留，依据 §12.239 |
| v4.186 | 2026-09-14 | OI-186：§9.3.3比例冷却由确认净成交启动、扫描只消费已启动状态；§11.5增加幂等成交凭据入口，扫描与回测共用消费及启动公式。依据 §12.238 |
| v4.185 | 2026-09-14 | OI-179：§8.3明确完整除权事件日历及停牌期再投时点；修复`exright_affine`、`daily_returns`和前向回报工具的报价日匹配遗漏，策略标记`ca2`，增加`test_suspended_actions.py`；BASE重登与斜率候选复核。依据 §12.237 |
| v4.184 | 2026-09-14 | §12.1 第10款明确股票×日期分布的重复观测，引用单票前向收益须并报MA60周期去重与同股窗口不重叠、区分锚止损计数，失败信号及不足窗口分列；新增 `pv_episode_forward.py`／`rank_episode_forward.py`，纠正 `selection_edge_audit.py` 口径说明。依据 §12.235 |
| v4.183 | 2026-09-13 | OI-178 结案：§6.8 增 SEC 标签组合规则——合并税前利润取合并标签、缺则境内＋境外或持续经营净利＋所得税（不得境内单项兜底）；有息负债分层只取一次（非流动债务／票据、`DebtCurrent` 流动合计、融资租赁，含租赁标签不叠加、经营租赁不计）；折旧摊销缺合计标签时折旧＋无形资产摊销；年报与 TTM 同规。落点 `fetch_overseas_statements.compose_sum`／`compose_debt`、`test_sec_tag_composition.py`；海外清单重建（11 家带变、甲骨文继续拒绝）。依据 [核验报告](reports/sec_tag_composition_2026-09-13.zh.md) |
| v4.182 | 2026-09-13 | OI-167 结案：回测引擎高价股一手兜底受单票上限余量约束（余量不足一手跳过、不触发卖出，与 §9.3.1／§9.3.1.1 成文及生产扫描器同判），策略名标记 `_cap0.6s`；新增 `test_position_cap_lot.py`；BASE 在册重登（轨道 A 护栏五项配对差中位全 0，旧 `cap0.6` 台账行保留）。依据 §12.233 |
| v4.181 | 2026-09-13 | OI-172／OI-173 结案：§12.1 第 2 款增判定前完整性校验（两表两臂起点集合＝标准起点集、同窗窗口集合相同、决策字段有限，否则不可判；共同覆盖只作诊断并单独标记）；`adoption_verdict`／`start_delta`／`_paired_median` 改严格口径（`pairing_defects`、`coverage`），否决改按「负窗占比由 0 转正」计数（`neg_window_flip`），决策表列改「负窗0→正」；历史 190 臂判定无翻转。依据 §12.232 |
| v4.180 | 2026-09-10 | §6.8 明确 SEC 纯利息费用逐期统一符号后合成 TTM、两条估值路径执行既有薄权益守卫并清空拒绝结果；修复 `fetch_overseas_statements.py`、`build_overseas_roic_bands.py`，重算全海外清单，并按官方维护行机制纳入 Adobe 当日 Q3 业绩三表。海外利息缺陷原重复编号 OI-175 更正为 OI-177，薄权益为 OI-176；依据 [修复核验](reports/overseas_valuation_fix_2026-09-10.zh.md) |
| v4.179 | 2026-09-10 | §6.5.1 增少数股权事件口径：按可得日登记同报告期合同请求权与完整股权桥，固定退出与存续权益去重、持股变化后的盈利份额重估、合并利润当期化；权利未核清则拒绝并阻断历史带回退，候选／B2／持仓／预告与档案同规。落点 `minority_claims.py`、`minority_claim_events.json`；依据 [OI-175核验报告](reports/oi175_minority_claims_2026-09-10.md) |
| v4.178 | 2026-09-10 | 采纳C030R35为后续BASE：§9.3.1低利差30%仓位约束与3.5pp恢复门槛、完整历史状态；§9.3.2/§10.2受限期间持续偿债与限买，个人体系§4同步。生产扫描器与回测共用`EquityBondConstraint.release_threshold`，BASE显式给恢复参数、策略名区分仓位和恢复线，美股基准不带；§10.3新增E3自2026-09-11执行、单位净值连续。依据§12.228～§12.229 |
| v4.177 | 2026-09-10 | §12.1 增融资约束替代规则研究入口：PE／历史分位、指数60月均线偏离、低利差仓位上限、滞回恢复与趋势／连续月确认；状态从完整历史重建，信号与全/A/U完整性检查独立留证，生产参数沿用。落点 `exp_equity_bond_opt_20260910`。依据 §12.227 |
| v4.176 | 2026-09-10 | OI-171 结案：用户裁定采纳股债总仓位上限——沪深 300 股债利差 < 3pp 时总仓位上限 100%（不新增融资、现金与卖出款先偿债、常规卖出后超限按持仓市值比例减仓、买入以买后总仓位 ≤ 上限为限），≥ 3pp 完整恢复。落点：§9.3.1 表、§9.3.2 第 4／5 步、§10.2、§12.1、§8 刷新命令、个人体系 §4；`SEC93_EQUITY_BOND_*` 与扫描器 `--cash`／`--debt`；引擎 `--equity-bond-restore-above`、`BASE` 显式带股债参数、`BASE_US` 不带；在册读数重登；策略纪元 `E2` 自 2026-09-10 起（§10.3 纪元表 `strategy_return_tracker.EPOCHS`）。依据 §12.224～§12.226 |
| v4.175 | 2026-09-10 | §12.1 第 2 款增回撤通道：主读数两表均 ≥ −1pp、复利两表均 ≥ −0.15pp、全期最大回撤配对差两表均 ≤ −5pp、滚 5 最差（全样本）≥ −0.15pp、候选更浅 ≥ 5pp 的 `BASE` 回撤段（两表合并按重叠归并）≥ 2 → 可采纳·回撤通道；闸门／否决照旧。判定收拢为 `sweep_backtest_configs.adoption_verdict`（dose_table／oi148 报表调用），【采纳判定】表增 ΔMDD／Δ滚5最差／回撤段列。依据 §12.224 |
| v4.174 | 2026-09-10 | 轨道 A 记账修复：日末盯市对当日新建仓取成交日收盘（OI-169）；买入委托含费税须在现金＋剩余授信内、最终委托按手缩量、同日对冲退回卖出款先在授信内融回（OI-170）；summary 与扫描文件增 `最低现金`／`最低现金日`／`负现金日数`，跨起点尾部同报。落点：§12.1 第 2 款「资金记账」、`backtest_valuation_strategy`（affordable_amount／affordable_shares／net_off_sale）、`sweep_backtest_configs.FIELDS`。BASE 与在评候选（OI-171）按 m3 同批重算，在册读数重登，OI-169/170 结案。依据 §12.223 |
| v4.173 | 2026-09-10 | §12.1 第 2 款主读数改为同起点同窗口滚 5 CAGR 配对差（先相减、起点内中位、再跨起点中位），计量版本 m2→m3；滚 5 中位配对差留标准指标集只描述；summary 增 `滚动5年窗口年化`、扫描文件增 `#WIN5` 行；阈值、双表判定与其余读数不变；m2 读数只读，BASE 与在评候选待 OI-169/170 修复后同批重算。落点：§12.1、`backtest_valuation_strategy.METRIC_VERSION`、`sweep_backtest_configs`、dose_table／ex_winner_symmetry_report／oi148_slippage_report／scan_plateau。依据 §12.222 |
| v4.172 | 2026-09-09 | §12.1新增股债性价比研究约束：月度利差/历史分位、停新增融资或总仓位上限、0～160%连续映射、T+1及费税整手守卫；生产缺省关闭；盯市/负现金偏差登记OI-169/170，利差3pp机械U资格记OI-171。依据§12.220 |
| v4.171 | 2026-09-09 | 增加横截面前q比例的买入研究开关与信号日分母、公司数取整、执行约束及报告纪律；生产缺省关闭。落点：§12.1、回测引擎与测试。依据 §12.219 |
| v4.170 | 2026-09-09 | §12.1 明确固定估值与股票池时的买入线独立剂量扫描不作合格面对齐，逐档报告实际比例及全/A/U对照；生产参数按原采纳程序处理。依据 §12.218 |
| v4.169 | 2026-09-09 | OI-168 结案：§6.3 第 6 条生产营运资金口径改 `operating`（`RoicYear.working_capital` 与建带缺省同此，原累加改名 `working_capital_legacy` 只作复现）；§6.7 建带命令加 `--wc-aggregation operating`，两侧逐日状态与展示链重出；§12.1 买入线对齐加容差 0.2pp（`align_buy_line.py --tolerance-pp`／`--registered-share`、`test_align_buy_line.py`），买入线 1.0454 容差内保留、换仓边际七档重扫维持 0.15；`check_swap_margin_scale_drift.py` 基准 0.0164/0.175 → 0.0196/0.186；在册重登。依据 §12.217 |
| v4.168 | 2026-09-09 | §6.3第6条统一营运资金科目归并与冲突诊断，新增含经营性应收款项融资的operating研究口径；默认legacy兼容，OI-168保留生产迁移与残余源核验，依据§12.216 |
| v4.167 | 2026-09-09 | §6.5.4 新增默认关闭的维持性现金占用研究入口，贯通ROIC输入、折现及现金拒绝事件；新增营运资金合计/明细互斥研究口径，登记OI-168，生产与BASE保留。依据 §12.215 |
| v4.166 | 2026-09-08 | 精简执行文档、个人体系及评分细则，删除重复 CONTEXT 与 ADR；历史校准和研究原文标明用途；池外待判断档案不标 L4；移除人工估值覆盖入口，档案写入按信号日截止读取利率并统一除权；刷新档案模板与跨轮次索引，校正海外显式待判断状态。审计见 `docs/reports/repository_cleanup_2026-09-08.zh.md` |
| v4.165 | 2026-09-08 | OI-166 取消后续美股复核并归档，待处理清零；已知限制与证据保留。处置见 §12.212 |
| v4.164 | 2026-09-08 | OI-150 完成原预登记全量执行与数据前提审计，以不可判结案；按CIK复用完整源价格、时点财报与缺失门槛，正式入口接入审计实现；登记美股补充分档输入缺陷OI-166，生产规则不改。依据 §12.211 |
| v4.163 | 2026-09-07 | OI-160/161/163/164 因赢家剔除K剂量不同向不采纳结案，生产与BASE不改；剂量文件写计量头，报表按比率单位检验并拒绝缺路径；OI-150 保留搁置并更正原预登记完成性表述。依据 §12.209–210 |
| v4.162 | 2026-09-07 | OI-162 统一扫描、持仓跟踪、阅读版与成交估值的银行/保险入口；利率按信号日过滤，缺失输入显式无值；新增成交估值命令与回归检查；OI-165 按原入池日补接九家判定源，面板装配缺员非零退出。依据 §12.207–208 |
| v4.161 | 2026-09-07 | 固定金额清尾研究开关 `--residual-clear-cny`、最终净卖单检查 `--residual-clear-final`（默认关闭），新增回测与佣金复核作业、边界和并单测试；§9.3.2、生产及 BASE 不改，登记 OI-164 待考察。依据 §12.206 |
| v4.160 | 2026-09-07 | 余仓清空剂量研究开关 `--residual-clear-tranches`（默认关闭），新增边界测试、两套 SLURM 作业与成交复核；§9.3.2、生产扫描器及 BASE 不改；0.1／0.25／0.5 档登记 OI-163 待考察。依据 §12.205 |
| v4.159 | 2026-09-07 | §5.4 银行口径「最优者」改「最优梯队」（十年 ROE 中位与稳定性同处第一梯队者均保留）；关注池护城河逐家审核后 37 家 `worth_attention → boundary_pending`（三类表、分层表、`verdicts_pit_moat_v6.csv` 出场日、核心池重建），`build_moat_panel.py` 支持 `worth_to` 取具体日期与银行行截断；报告 `docs/reports/moat_audit_2026-09-07.zh.md` |
| v4.158 | 2026-09-07 | 用户点名复核中国船舶／中金公司：两家维持 boundary_pending 并建池外档案（§6.1）；中国船舶三大报表并入面板；新增 `scripts/slurm/rebuild_chain_with_fetch.sbatch`（§6.7 第 1-3 步一体作业，`SIGNAL_DATE`／`SINCE`／`EXTRA_CODES` 环境变量） |
| v4.157 | 2026-09-07 | 标普 100 历史成分面板脚本 `build_us_sp100_panel.py`（Wikipedia 修订历史 → 区间 → 标普 500 成员表取 CIK）、作业 `scripts/slurm/us_sp100_panel.sbatch`、配置 `configs_us_sp100.txt`；研究用，§9.3.1 与 BASE 不改。依据 §12.203 |
| v4.156 | 2026-09-06 | 美股市场层（研究，不入生产）：引擎 `--market us`、`--withholding-rate`（固定预提），`--exclude-codes` 收 10 位 CIK；扫描器 `--market us`（`BASE_US`、9 个半年起点、锚 2012-05-01）；脚本 `build_us_index_panel.py`、`fetch_us_ohlcv_history.py`、`fetch_us_rates.py`、`fetch_us_companyfacts.py`、`build_us_daily_states.py`、`experimental/us_h1_readout.py`、`experimental/align_buy_line.py`；`fetch_overseas_statements.py` 股数与归母权益兜底；`panel_tier_forward.py` 加 `--ohlcv-dir`／`--actions`；作业 `scripts/slurm/us_sp500_*.sbatch`。§9.3.1 与 BASE 不改；OI-159 结案（不支持 H1）。依据 §12.202 |
| v4.155 | 2026-09-06 | OI-157 按用户裁定不采纳结案；`--t1-judge gain` 留研究开关，§9.3.1、生产常量与 BASE 不改。依据 §12.201 |
| v4.154 | 2026-09-06 | 剔除集运行的集合标签改为 `<集合>@<挑战臂>`（`ex_winner_symmetry.py`；`ex_winner_dose.py` 新增必填 `--challenger`，K 标签同式；`ex_winner_symmetry_report.py` 兼容旧文件），赢家名单可回读现行台账；扫描台账归并键加 `计量版本`（`clean_derived_artifacts.py`，测试 `test_scan_ledger.py`）；现行台账旧式集合标签行按新标签重跑替换。OI-158 结案。OI-157 §12.1 第 4 款三项补齐（作业 `scripts/slurm/oi157_t1gain_sweeps.sbatch`／`oi157_t1gain_signal.sbatch`，配置 `data/experiments/exp_t1_info/configs/t1gain_*.txt`），§9.3.1 与 BASE 不改、待用户裁定。依据 §12.201 |
| v4.153 | 2026-09-06 | 研究开关 `--stop-basis both`（止损两时点任一跌破）与 `--t1-judge gain,swap,buy`（涨幅减持／换仓卖出源／合格集只按 T+1 收盘判），缺省不变；作业 `scripts/slurm/t1_info_sweep.sbatch`、`t1_info_exwinner_u.sbatch`，测试 `scripts/test_t1_judge.py`；止损 T 日判／两时点、其他操作零延迟、T+1 确认重跑九臂均不采纳，§9.3.1 止损行与 BASE 不改；T1_GAIN 按 §12.1 第 4 款登记 OI-157 待考察。依据 §12.200 |
| v4.152 | 2026-09-06 | 执行时点研究开关 `--exec-price open_sell_close_buy`（缺省不变）、四臂对照作业 `scripts/slurm/exec_timing_sweep.sbatch` 与配对脚本 `scripts/experimental/exec_timing_pairwise.py`；T 日收盘／T+1 开盘／T+1 开盘卖收盘买三臂不采纳，§9.3.1 执行时点与 BASE 不改。依据 §12.199 |
| v4.151 | 2026-09-06 | OI-156 按用户裁定不做结案；RF5（`--swap-chop-mode repeat-flat`）不采纳，§9.3.1、生产常量与 BASE 不改。依据 §12.198 |
| v4.150 | 2026-09-06 | 换仓震荡交集与重复净换出保护研究开关 `--swap-chop-*`（默认 off）；`swap_chop_guard.py`、联合复盘／相邻参数／成本与时期／事件普查／信号审计工具及 SLURM 作业；旧前向诊断改为区间内含现金分红收益。§9.3.1 不改；X3/X5 登记 OI-156。依据 §12.198 |
| v4.149 | 2026-09-06 | 换仓卖出源弱势的形态复核研究开关（缺省全关、逐位不变）：引擎 `--swap-weak-days`／`--swap-weak-slope`／`--swap-weak-slope-min`／`--swap-weak-max-cross`／`--swap-weak-cross-window`／`--swap-weak-deep`／`--swap-source-cooldown`、被挡事件记录 `--weak-block-log`；复盘脚本 `scripts/experimental/whipsaw_swap_diag.py`；作业 `scripts/slurm/whipsaw_swap_sweep.sbatch`／`whipsaw_swap_diag.sbatch`；测试 `test_swap_weak_regime.py`。§9.3.1 不改。依据 §12.197 |
| v4.148 | 2026-09-05 | §12.1 第 4 款比率项（滚 5／全期 Calmar、Sharpe）阈值定为比率单位 0.005（对应 −0.15pp）／0.033（对应 −1pp）。落点：§12.1 第 4 款、`oi148_slippage_report.py`。OI-151 结案；OI-145／OI-138 按用户裁定不采纳结案；OI-149 按用户裁定不实施结案 |
| v4.147 | 2026-09-05 | 执行成本压力档位（OI-148）：引擎 `--slippage-bp`（每边滑点，买加卖减，只进成交量，0 逐位不变）；扫描器 `--exclude-codes` 固定剔除集单遍，summary 先落进程私有目录再原子复制到 `data/backtest/`（并发扫描不再互删同名 summary、不再漏跑去赢家第二遍）；§12.1 第 7 款加采纳前必报的 0／10／20／30bp 同档配对、第 3 款指向固定剔除。另：备用清单配置生成器接受相对仓库根的 `--exp`，提交脚本显式 `--export=ALL,EXP`。落点：`backtest_valuation_strategy.py`、`sweep_backtest_configs.py`、`oi148_slippage_report.py`、`scripts/slurm/oi148_slippage.sbatch`、`make_shortlist_configs.py`、`submit_strategy_shortlist.sh`。依据 §12.193 |
| v4.146 | 2026-09-05 | 删除退役的海外旧建带器 `scripts/archive/build_overseas_dossiers.py` 与 `overseas_dossier_inputs.py`（PEG／implied_pe／ddm3／justified_pb 口径，v4.111 起不可 import，误跑会覆盖海外估值表）；海外估值只走 §6.8 的 `fetch_overseas_statements.py` + `build_overseas_roic_bands.py`。落点：`scripts/archive/README.md` |
| v4.145 | 2026-09-05 | 目录迁移补遗：16 个实验配置内路径改 `data/experiments/`；台账写入统一为 `clean_derived_artifacts.write_ledger()`，行按 `计量版本` 分流 `scan_summaries.csv`／`data/archive/scan_summaries_m1.csv` 并重建按臂索引，三个实验证据脚本改走该接口；核心池阅读版 L4 档案链接按输出文件所在目录算相对路径；`scripts/archive/` 脚本导入上级 `scripts/`、仓库根取 `parents[2]`。落点：`clean_derived_artifacts.py`、`build_a_share_core_valuation_pool.py`、`test_scan_ledger.py`、`docs/000_a_share_core_valuation_pool.md`。OI-152～155 结案。依据 `docs/reports/repository_structure_audit_2026-09-05.zh.md` |
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
