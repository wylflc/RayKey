# A股选股-估值-量价操作流程 v4.195

> 按任务路由执行。版本号由第 1 行读取；相关缺陷先查 `docs/000_Ashare_workflow_open_issues.md`。

## 0. 任务路由

| 请求 | 执行章节 | 主要入口 |
| --- | --- | --- |
| 今日 A 股每日扫描 | §9.1、§9.3、§11 | `screen_daily_volume_price_signals.py`、`track_holdings_daily.py` |
| 今日该买、加、减、换什么 | §9.3 | §9.3.1 参数表与 §9.3.2 顺序 |
| 今日持仓跟踪 | §11 | `track_holdings_daily.py --as-of` |
| 季度全市场质量审查 | §5.1-§5.4 | `build_quarterly_quality_review_queue.py` |
| 对 `worth_attention` 做 L1-L3 分层 | §5.7-§5.8 | `docs/Ashare_quality_rubric.md` |
| 更新估值与核心池 | §6 | §6.7 估值重建链 |
| 财报披露后的滚动更新 | §7 | `build_report_update_queue.py` |
| 单票研究（含点名建档与 L4） | §5 → §6 → §9.3 | 逐层判断，任一层否决即止 |
| 海外单票研究（港股／美股／韩股点名） | §5 → §6.8 | 逐层判断；建档、入清单、重出阅读版三步缺一不可 |
| 修改估值、交易规则或回测参数 | §12-§13 | `sweep_backtest_configs.py` |

所有可复核结论均按 §2 写入决策日志。买卖机制只认 §9.3；账户级风险只认个人投资体系 §4 的两条外生硬约束（券商授信额度、强平线）。

## 1. 目标与边界

执行原则：

1. 业务质量决定是否值得持续研究；价格和题材不进入质量判断。
2. 合理价区间只由基本面证据与模型改变；价格只改变当日 `P/V`。不得由希望得到的 `P/V` 反推合理价。
3. `P/V` 与走势条件按 §9.3 机械产生执行清单，不临时加入主观快速通道。
4. 流程终点是执行清单；实际下单由用户决定。
5. 原始数据、过程数据、当前结论和历史记录分开保存。
6. 同一口径在本文件只定义一次；其他章节和文档直接引用定义位置。

## 2. 唯一真值与固定产物

| 内容 | 唯一真值 |
| --- | --- |
| A 股证券名单 | `data/raw/a_share_securities.csv`；历史快照在 `data/raw/snapshots/`，不可修改 |
| 三类初筛 | `data/processed/a_share_attention_triage.csv` |
| 质量分层与参考分 | `data/processed/a_share_watchlist_quality_tiers.csv` |
| 逐票研究档案 | `data/processed/a_share_valuation_dossiers.csv` 与 `data/companies/<代码>_<名称>/` |
| 当前生产模型带 | `data/processed/a_share_pool_model_bands_adopted.csv`（候选侧） |
| 持仓侧模型带 | `data/processed/a_share_pool_model_bands_hold.csv`（逐票取候选侧与 B2 较高 V；§9.3.1 换仓来源读它） |
| 核心估值池 | `data/processed/a_share_core_valuation_pool.csv` |
| 核心池阅读版 | `docs/000_a_share_core_valuation_pool.md` |
| 持仓 | `data/processed/a_share_holdings.csv` |
| 持仓除权处理台账 | `data/processed/holdings_corporate_actions_applied.csv`（§11.4，只追加） |
| 账户快照 | `data/processed/portfolio_account_snapshot.csv`；可用资金按 §10.2（券商可用保证金优先），策略收益率、峰值与回撤按 §10.3 |
| 每日买入计划 | `data/processed/daily_entry_plan.csv` |
| 每日卖出清单 | `data/processed/daily_sell_plan.csv`（止损复核、涨幅减持、出名单、换仓、余仓清空） |
| 比例冷却计数器 | `data/processed/daily_cooldown_state.csv`（§9.3.3，扫描器每日读写） |
| 比例冷却成交凭据 | `data/processed/cooldown_executions.csv`（§9.3.3，用户确认的净成交，只追加） |
| 每日持仓跟踪 | `data/processed/daily_holdings_tracking.csv` |
| 每日阅读日志 | `docs/000_daily_scan_log.md` |
| 审计日志 | `data/processed/a_share_workflow_decision_log.csv`，只追加不覆盖；核心池重建每次写一行汇总，逐票只在 `pool_layer` 变化时写行；换纪元时把旧纪元行移入 `data/archive/decision_log_<起>_to_<止>.csv`（公司分析索引同读） |
| 财报更新队列 | `data/interim/a_share_report_update_queue.csv` |
| 每日行情与两侧 P/V | `data/processed/daily_buy_candidates.csv`（§8.2；`--since auto` 由它检出上次扫描日） |
| 执行计划发布凭据 | `data/processed/daily_execution_publication.json`（§9.1 第 5 步成功凭据，`daily_execution_guard.py` 发布与 `verify`）；同日证据凭据 `data/interim/daily_evidence_<日期>.json` 及公告、公司行动、市场背景快照 `data/interim/daily_{announcements,corporate_actions,market_context}_<日期>.json` |
| 逐日估值状态与带（§6.7 第 2～4 步产物） | 候选侧 `data/processed/a_share_daily_states_adopted.csv`、`roic_bands.csv`、`roic_daily_raw.csv`；B2 `a_share_daily_states_b2.csv`、`roic_bands_b2.csv`、`roic_daily_raw_b2.csv`、`a_share_pool_model_bands_b2.csv`；持仓侧 `a_share_daily_states_hold.csv`；回测宇宙 `data/processed/pit_attention/panel_moat_bank_v6b.csv` |
| 估值表与人工台账 | `data/processed/a_share_focus_watchlist_l1_l2_valuation.csv`（§6.7 第 5 步）；`data/processed/entity_reset_dates.csv`、`share_event_reviews.csv`（§6.5.2.4，人工登记） |
| 海外关注清单估值 | `data/processed/overseas_watchlist_valuation.csv`（§6.8） |
| 影子组合 | `data/processed/shadow_portfolio/since_20260828/`（§10.4 主比较；`e4/` 只作分段对照） |
| 公司分析索引 | `data/processed/a_share_company_analysis_index.csv` 与 `a_share_company_analysis_index.md`（`build_a_share_company_analysis_index.py` 读当前与归档决策日志生成；§6.7 第 2 步的行业口径读它） |

每条质量、估值、名单迁移、规则采纳或成交结论必须写入决策日志，至少包含：时间、阶段、对象、结论、简要理由、输入文件、输出文件、执行者、工作流版本和稳定 `decision_id`。纠错或替代旧结论时填写 `supersedes_decision_id`。

## 3. 核心术语

| 术语 | 定义 |
| --- | --- |
| `worth_attention` | 通过 §5 三类初筛、进入持续研究的公司集合；它不是买入清单 |
| `boundary_pending` | 证据不足或当前缺乏持久优势、但保留硬触发复核可能的公司 |
| `documented_not_attention` | 用户点名建档、经分析判无护城河的公司：有档案、L4 分层、参考分与估值区间，但不在 `worth_attention`，一律不可买（§10.1 第 1 条） |
| `garbage` | 仅因坐实治理灾难或结构性绝望行业而永久排除的公司 |
| L1/L2/L3/L4 | §5.7 的业务质量分层；不直接决定买入资格（不可买由名单归属决定） |
| 合理价 `V` | §6 当前生产带上下沿的中值 |
| `P/V` | 未复权现价 ÷ `V`，交易规则使用的估值比率（唯一实现 `scripts/pv_ratio.py`，扫描器／跟踪器／阅读版／档案同源）；薄权益带（净负债 ≥ 50% 企业价值）按 §6.5.1 守卫判无法估值、无 `P/V` |
| 空间 | `V ÷ 现价 − 1`，仅作阅读展示 |
| 合格集 | 通过 §9.3.1 买入线、走势条件、冻结与 L3 战术闸门的股票，按 `P/V` 升序 |
| 一档 | 按 §9.3.1.1 从当日净资产计算的单次交易金额 |

## 4. 总流程

```text
A股证券名单 ∪ 财报中出现的A股证券
  → §5 三类初筛
  → 对 worth_attention 做 L1-L3 分层
  → §6 建立并校验生产模型带
  → §7 根据披露与事件滚动复核
  → §8 取得收盘、MA20、MA60、P/V、相关性
  → §9.3 先卖后买，生成 T+1 尾盘执行清单
  → 用户成交后按 §11.5 回写
  → §11 每日跟踪持仓
```

## 5. 阶段一：质量审查

### 5.1 频率

每个季度报告披露周期后做一次全量更新；财报季内按披露滚动复核。

### 5.2 证据要求

质量判断按以下优先级取证：

1. 定期报告、公告、监管文书、交易所问询与投资者关系材料。
2. 权威机构或专业研究报告。
3. 同行公司披露、行业协会和政策文件。
4. 聚合站与 F10 只作线索，不作结论证据。

判断必须逐家公司完成；脚本只生成队列、连接数据和校验覆盖，不得用阈值批量决定最终类别或层级。

### 5.3 更新证券名单与队列

季度开始先更新证券名单：

```bash
python3 scripts/fetch_a_share_universe.py \
  --output data/raw/a_share_securities.csv

# 队列的财务判据读 data/raw/financials/ 逐季面板，建队列前先增量刷新到当日
python3 scripts/fetch_a_share_quarterly_financials.py --signal-date YYYY-MM-DD --since <当前报告期末> --refresh

python3 scripts/build_quarterly_quality_review_queue.py \
  --market A_SHARE \
  --as-of YYYY-MM-DD \
  --universe data/raw/a_share_securities.csv \
  --attention-triage data/processed/a_share_attention_triage.csv \
  --previous-tiers data/processed/a_share_watchlist_quality_tiers.csv \
  --output data/interim/a_share_quarterly_quality_review_queue.csv
```

证券名单必须保留来源字段并生成不可变日期快照。新股若披露不足，先进入 `boundary_pending`，不得因资料少判为 `garbage`。

**新股入池判定挂在每个季度报告法定截止日（4-30／8-31／10-31／次年 4-30）后的全量更新里**：名单刷新检出的上市新股由队列的 `new_or_unreviewed_security` 触发承载，当批逐一完成 §5.4 三类初筛并写决策日志——已披露至少一份定期报告（或招股书数据足以做资本复制测试）的当批判定；披露仍不足的按上款留 `boundary_pending`，**并在下一个季度截止日批次强制重判**，不得无限期滞留未判状态。

### 5.4 三类初筛

| 类别 | 判定 | 后续 |
| --- | --- | --- |
| `worth_attention` | 优势持久、难以被资金快速复制，且能转化为定价权、成本优势、客户锁定、网络效应、稀缺资源或超额回报 | 进入分层、估值和每日扫描 |
| `boundary_pending` | 证据不足；或可判断但当前没有足够持久优势，行业仍存在改善可能 | 只在硬触发后复核，不进入每日扫描 |
| `garbage` | 坐实造假/重大治理灾难；或行业/子行业结构上不可能形成持久优势 | 永久排除，只维护证券信息 |

共同规则：

1. 先做资本复制测试：核验资金充足的新进入者能否主要靠投入资本快速复制能力、替代公司并侵蚀回报；存疑不进入 `worth_attention`。
2. 股价、估值、市值、主题热度和短期盈利不影响三类判断。
3. 公司层面平庸但行业并非结构性绝望，判 `boundary_pending`，不判 `garbage`。
4. `garbage(governance_fraud)` 必须有行政处罚、司法文书、审计意见或交易所处分等权威证据；仅有嫌疑时判 `boundary_pending` 并写核验触发。
5. 同业对比必须检查差异化位置；“不如第一名”不等于被全面覆盖。
6. 行业增长放缓本身不是初筛排除项；只在壁垒载体被破坏时影响质量。

行业特殊口径：

| 场景 | 操作口径 |
| --- | --- |
| 规制基础设施、普通银行、极端牌照业务 | 只有不可复制性已持续转化为高于同业的回报，才可进 `worth_attention` |
| 银行 | 关注池只保留系统重要性代表和长期 franchise 质量最优梯队（十年 ROE 中位与稳定性同处上市银行第一梯队者均保留）；普通规模型银行留 `boundary_pending` |
| 保险 | 同银行口径：只保留系统重要性代表与长期 franchise 质量最优者——判据为**十年维度** ROE 中位与稳定性高于同业（短期同业 ROE 受权益投资收益推高不作数）；普通寿险留 `boundary_pending` |
| 商品与资源 | 同时要求稀缺/配额、成本曲线和规模/储量；仅有其中一项不足以入选 |
| 资本密集周期制造 | 结构整合、技术、规模或准入壁垒已使替代客观困难时可以入选；景气本身不算壁垒 |
| 客户集中 | 区分可竞争买方与结构性单一买方；后者须有长认证、准入锁定和稳定长期 ROE，前者须证明能力可跨客户迁移 |
| 受困或 ST | 未坐实造假时按竞争力判断；控制权已更换且责任人出清时允许回到 `boundary_pending` 复核 |

读取 `docs/peer-group-calibration/` 时，只将其作为历史研究线索；核对原始证据与当前结构化名单后用于同业比较，不按其中的保留名单或筛选条文执行。

### 5.5 状态迁移

| 迁移 | 触发 |
| --- | --- |
| `worth_attention → boundary_pending` | 持久优势证伪或资本复制测试不再通过 |
| `worth_attention → documented_not_attention` | 复核判定不存在护城河载体；**判定主体是名单迁移**，分层随之记 L4 |
| `worth_attention → garbage` | 坐实治理灾难或行业被证实结构性绝望 |
| `boundary_pending → worth_attention` | 财报、订单、客户验证、产品、重组或行业结构等硬触发后重新通过测试 |
| `boundary_pending → documented_not_attention` | 用户点名建档且分析结论为无护城河（§6.5.2 建档义务随之成立） |
| `boundary_pending → garbage` | 坐实治理灾难或结构性绝望 |
| `documented_not_attention → worth_attention` | 硬触发后重新通过资本复制测试（与 `boundary_pending` 同通道） |
| `garbage → boundary_pending` | 仅限原证据被权威信息推翻、责任人出清，或子赛道被证明结构不同 |

质量分层不能改变 `attention_class`：L3→L4 降档必须作为一次 `attention_class` 迁移判定并携带证据。任何迁移均写决策日志；纠错必须关联旧 `decision_id`。

### 5.6 复核队列条件

满足任一条件进入队列：新上市；新报告晚于上次复核；原 L1/L2；L3 出现经营或技术改善；`boundary_pending` 出现硬触发；关键利润率、现金流或增长发生重大变化；发生诉讼、处罚、审计或控股股东风险。

`garbage`、无硬触发的 `boundary_pending`、以及只有价格或传闻变化的公司不进入队列。

### 5.7 L1-L3 质量分层

| 层级 | 判定 |
| --- | --- |
| L1 强护城河 | 通道 A：Q2 ≥ 82 且 Q1 ≥ 66；或通道 B：Q1 ≥ 80 且 Q2 ≥ 78；同时不存在成立的中/高概率侵蚀路径 |
| L2 中护城河 | 未过 L1，且未触发 L3；这是默认层级 |
| L3 弱护城河 | 被更强同行全面覆盖且无不可替代利基；或 Q2 < 66；或 Q1 < 60 且 Q2 < 72 |
| L4 无护城河 | 仅出现于 `documented_not_attention` 公司：资本复制测试不通过——定价权、成本优势、客户锁定、网络效应、稀缺资源中不存在任何持久载体，或载体已被证实丧失。判语须点名缺失的载体、给出可指事实（利润率结构、份额、复购或认证证据），并与至少一个同业锚对照；印象式的「比较差」不构成 L4 |

L4 行须记 `l4_since`（首判日期）；连续一年仍为 L4 的停止复核——留档、留在 `documented_not_attention`、不再进任何队列，复活仅经 §5.5 硬触发通道。

评分细节见 `docs/Ashare_quality_rubric.md`。参考分只用于同层排序：

```text
参考分 = Q1×0.25 + Q2×0.40 + Q3×0.20 + Q4×0.15 − 报表可信度扣分
```

硬规则：

1. 只对 `worth_attention` 与 `documented_not_attention`（后者必为 L4）评分；价格、估值、市值、流动性和当前景气不入分。`boundary_pending` 与 `garbage` 不评分。
2. 每个维度、扣分、旗标和最终层级必须有理由与来源。
3. Q3、Q4 只进参考分，不直接决定层级；参考分不得自动决定买入或仓位。
4. 分数和层级只凭新证据改变，不按预设分布配名额。
5. `a_share_watchlist_quality_tiers.csv` 是全部分层字段的唯一结构化真值，不另建平行打分表。
6. `special_advantage_check` 必填，用于检出战略角色、章程承诺、事实标准等非标准优势载体。

侵蚀路径成立须同时满足：路径具体；不是行业普遍风险；中/高概率及影响有事实依据；与同档锚点执行一致。四项逐条写入 `tier_reason`。Q1 或 Q2 位于层级边界 ±1 分时，必须列至少一个同档锚点逐项对照。

市场结构性缩量只有同时满足以下四项，才进入 Q2 并最多下调一层：行业总量而非公司份额下降；连续至少三个完整年度且距峰值至少下降 30%；最近年度仍下降且无可说明的企稳路径；定价权、规模经济或交易结构等壁垒载体已被削弱。否则只在估值与研究备注处理。

### 5.8 质量审查执行步骤

1. 描述主要业务、利润来源与业务结构。
2. 识别护城河载体并执行资本复制测试。
3. 与同业和既有锚点比较，检查不可替代利基。
4. 列出未来两至三年的具体侵蚀路径、概率、影响与证据。
5. 先确认 `attention_class`，再对 `worth_attention` 做分层。
6. 输出观察池动作、复核触发和证据日期。
7. 写入三类表、分层表和决策日志。

最少输出字段：代码、名称、`attention_class`、`quality_tier`、`moat_summary`、资本复制结论、同业比较、类别理由、层级理由、复核触发、证据来源、`evidence_available_at`、复核时间和工作流版本。

## 6. 阶段二：估值与核心池

### 6.1 执行范围

对全部 `worth_attention` 公司维护估值带。用户点名的任何公司也建档并给出估值区间（含结论为 L4 者，§6.5.2）。用户点名建档但未进入 `worth_attention` 的公司，在 `docs/000_a_share_core_valuation_pool.md` 的池外档案区列示；名单状态取三类表，质量档取分层表，`boundary_pending` 与 `garbage` 不显示档位或分数；合理价只读逐票档案，不入池 CSV、不落生产带文件、无 `P/V`、不取每日行情、不进扫描与 §9.3 的任何判定。估值只生成合理价 `V`；买卖资格由 §7 的冻结状态和 §9.3 决定。

### 6.3 数据与时点

1. 建带输入不得包含当日现价、现市值、当前 PE 或当前 PB；股本可以用同一时点的总市值÷现价取得。
2. 财务数据按可得日 `available_at` 生效，禁止用报告期末代替可得日。**可得日 = `min(记录公告日, 法定披露截止日)`**（年报次年 4/30、一季报当年 4/30、半年报 8/31、三季报 10/31；唯一实现 `scripts/disclosure_dates.py`）。**被追溯重述的报告期按版本生效**：重述前版本用至重述后值的可得日（存档列 `superseded_at`），其后用重述后版本；无重述前版本存档的期，可得日取 `max(原可得日, 重述可得日)`。存档由 §6.7 第 1 步取数脚本在覆盖旧行前写入：三大报表 `data/raw/financials_statements/superseded/<表>.csv`（`superseded_at` = 远端新 `UPDATE_DATE`）、逐季面板 `data/raw/financials/superseded/<报告期>.csv`（`superseded_at` = 重取的证据日）；重述日志 `data/interim/statement_restatements.csv`。面板无存档而三表有存档的期，面板重述前版本由三表存档推得（`bps = 重述前归母权益 ÷ 股本`，EPS／归母净利／营收取重述前利润表）。
3. 季报财务为累计口径；单季值用同年累计差分，TTM 用最近四个单季求和。
4. 一致预期使用逐份研报归母净利润中位数，覆盖少于三家时不得采用；禁止混用送转前后的研报 EPS。
5. 跨字段比率必须使用同一披露口径；字段缺失时整体退回上一套已披露口径，不拼接半新半旧的数据。
6. **经营营运资金的科目归并（OI-168）**：应收/应付组有合计时取合计，合计缺失才取同一报表行的明细和，不叠加二者；合计与明细冲突时保留合计及冲突诊断，不以混入次年期初、旧主体或旧分类的明细强行补齐。经营性应收款项融资 `FINANCE_RECE` 独立计入资产侧；旧票据字段被归入新融资应收且合计已排除它时，只承接新分类一次。存货、预付、合同资产及经营负债沿用现有范围。唯一实现 `roic_inputs.working_capital_inputs`；同一已披露三表版本内归并，再依第2条选择历史版本。生产口径 = `--wc-aggregation operating`（`RoicYear.working_capital` 与建带缺省即此口径，§6.7 命令显式给出）；`reported`（仅去重）与 `legacy`（合计与明细相加，`RoicYear.working_capital_legacy`）只作研究复现开关，不得用于生产带与 `BASE`。核验设计与采纳证据见 `data/experiments/exp_oi168_wc_20260909/preregister.md`、`data/experiments/exp_oi168_land_20260909/preregister.md` 及回测日志 12.216～12.217 节。

### 6.4 预告与快报的叠加

预告与快报只有在公告已发生、尚未被正式报告取代且报告期已实质走完时进入锚；快报优先，区间取中值。执行点是 §6.7 第 4 步的 `apply_forecast_band_overlay.py`。叠加只走 `bps` 通道——预告的归母净利经留存收益改变每股净资产，`nopat_ps = ratio0 × BPS_op` 与 `eps0 = roe0 × BPS_op` 随经营账面等比缩放（缩放基数为 `bps_operating`，外生权益 `x` 不动），**归一化锚 `ratio0`／`roe0` 不动**；净负债不调整（预告无资产负债表）。正式报告披露后由机械带自然取代。

### 6.5 当前估值方法

策略标签只用于研究分类和展示，不选择生产估值模型。标签定义以个人投资体系 §5 为准；所有 A 股生产带统一走本节模型。

#### 6.5.1 唯一生产模型

生产估值只有一个入口（§6.7 建带命令），按输入可得性与企业性质分四条路径，带文件 `roic_path` 列逐行标明；读跨票比较结论时先看该列：

1. **growth（主路径：非金融且三大报表 ≥3 个财年）**——ROIC/FCFF 内在价值：NOPAT、投入资本、增量 ROIC（五年窗首尾 `ΔNOPAT/ΔIC`）、再投资率、WACC、增长衰减和净负债共同生成每股价值；`g0` 取资本腿 `min(增量 ROIC, 40%) × 再投资率` 与利润增速腿（NOPAT 五年 CAGR）之**大者**、夹 `[0, 25%]`，带文件 `roic_g_source` 列标明实际来源；终值 `ROIC_T = min(WACC + 2pp, ROIC0)`。**每股 NOPAT 的归一化比率 `ratio0`**：①**增长态信任度** `λ = 近两次年度变动中上行的次数 ÷ 2 ∈ {0, ½, 1}`，非周期锚 `= 三年比率中位 + λ × (当期比率 − 三年中位)`；②**周期守卫坡道** `w = clip((当期比率 ÷ 十年中位 − 1.3) ÷ 0.6, 0, 1)`（十年中位 ≤ 0 时 `w = 0`），`ratio0 = (1−w) × 非周期锚 + w × 五年比率中位`，利润增速腿 `× (1−w)`；**谷底对称守卫** `v = clip((十年中位 ÷ 当期比率 − 1.3) ÷ 0.6, 0, 1)`，取 `max(w, v)` 作混合权重；带文件 `peak_weight`／`growth_trust`／`trough_weight` 三列留痕，`roic_nopat_mode` 在两端记 `ttm_growth`／`median3`／`cyclical_median`、中间记 `blend(λ,w)`。**季报期间的当期化与增速腿折减**：季报行的当期比率 = 年报最新比率 × `归母净利 TTM ÷ 年报归母净利`（TTM = 年报 + 本期 YTD − 上年同期 YTD；年报行恒为 1；年报净利 ≤ 0、季报缺行或年报滞后一年以上时不算），信任度 λ 与三年/五年中位仍取年报、守卫坡道 `w` 按 TTM 当期重算；增速腿另乘 `d = min(1, NOPAT_最新/NOPAT_上年) × min(1, TTM 因子)`；带文件 `ttm_factor`／`growth_damp` 两列留痕。**B2 口径（持仓侧带的第二输入，建带命令另加 `--ttm-trust on --ttm-trust-delta 0.02`）**：季报行的 λ 改按 {年报₋₁→年报₀, 年报₀→TTM} 两次变动计（TTM 一步 `TTM 因子 ≥ 1.02` 记上行、`≤ 0.98` 记下行、其间沿用年度 λ；极低比率保护不变），其余与候选侧同式。
2. **zero_growth**——`ROIC0` 距 `g_T` 不足利差护栏时退零增长锚：`V = 每股NOPAT ÷ WACC − 每股净负债`。
3. **equity_fallback（非银行金融企业；无三大报表者）**——同一折现引擎喂权益口径：`roe0 = 归一化ROE + 2×(TTM − 归一化ROE)`（仅当期高于归一化时上抬，onesided_max λ=2）、`eps0 = roe0 × BPS_op`（清洁盈余；`BPS_op` 与外生权益见下文股本口径段）、`g0 = roe0 × (1 − 近三年派息率)` 夹 `[0, 25%]`、`ROE_T = min(12%, roe0)`。
4. **bank_divspread（银行与保险）**——`V = 最近已知完整财年每股现金分红合计 ÷（十年期国债收益率 + 2%）`。每笔现金分红按东财 `report_date`（分红所属报告期）归入财年，自董事会预案公告日（`plan_notice_date`，缺失时退除权日）起计入；财年在「已知该年 12-31 期分配」或「已过次年 4-30」之一成立时算完整，取最新完整财年，合计 ≤ 0 判无法估值。分子实现唯一落点 `scripts/divspread_dividend.py`，历史逐日与实盘扫描同读。天然现价口径，除权归一化对银行/保险行跳过（§6.5.2.3）。保险与银行同口径；名单与名称判定统一在 `scripts/divspread_names.py`。

**每股锚的股本口径**：两条非银路径的每股分子 = 归一化比率 × 当期经营每股净资产；增发／配股／H 股／可转债转股（+）与回购注销（−）形成的外生权益不得按比率放大，按以下口径处理：

1. **经营账面 `BPS_op` = 当期 BPS − 外生权益/股 `x`**；`x = BPS_当期 − (最新年报母公司权益 + 其后归母净利 − 其后现金分红) ÷ 当期股数`；「其后现金分红」= 除权日在 (年报期末, 本期期末] 的现金分红，加上已结束财年的年度分配中预案公告日 ≤ 本期期末、除权日晚于本期期末者（仅本期为 06-30 或 09-30 行）；预案公告日 ≤ 年报期末而除权日在其后的中期分红、预案在本期内而除权日晚于期末的中期分红，逐笔按使 `|x|` 更小的解释决定是否计入；每股现金按同日及其后的送转折到本行 BPS 的股本基准；股数 = 年报期末股数（年报权益 ÷ 年报 BPS）× 期间送转因子；「归母净利 ÷ EPS」隐含股数的**相对年报行的倍数**承接稀释／注销的股数变化，采用前先除掉本行之后各次送转的累计因子，且须同时满足三道守卫：EPS 小数位精度（舍入误差 ≤2%）、账面先动（`|x_假定| ≥ 3% BPS`）、方向一致（增发 x>0 且股数增／注销 x<0 且股数减）。合理性边界：`x ≤ 95% BPS`（封顶）、`x < −25% BPS` 视为主体重述／数据错位不调整（记 `x_implausible_negative`）。年报行 `x = 0`；年报行 BPS 被按后来的送转折到之后股本的，由 `bps_restated_factor` 按上一行核对并乘回当时口径。
2. **年报之间的外生权益逐年识别**：`X_y = ΔE − (归母综合收益 − 现金分红)`（无综合收益时用归母净利），只计 `|X_y| ≥ 5%` 上年母公司权益的年份。比率窗口与十年守卫窗口内各年比率一律按**经营账面** `E_op = E − 未花的募资 − 累计注销` 计，增长态／中位／周期守卫同式。「未花的募资」按先进先出判：每笔募资只在「超额现金较募资前一年持续高出的部分」内算未花，一旦回落即视为已投入经营、此后积累的现金是经营所得（与 ROIC 路径「投入资本剔除超额现金」同一口径）；注销的现金已流出，经营账面按注销前计。**结构断点**：某年 `E_op < 20% × E`（或权益 ≤ 0）时，比率窗口与十年守卫窗口一律从该年重起。权益退路（无三大报表）只做第 1 条。
3. **外生权益按面值进每股净现金，少数股东按盈利份额扣减**：ROIC 路径 `每股净金融负债 fin_nd = (有息负债 − 超额现金) ÷ E_op × BPS_op`，`少数股东扣减 = max(少数股东权益 ÷ E_op × BPS_op, m × (EV − fin_nd))`，`m` = 比率窗口内合并净利为正财年的 `少数股东损益 ÷ 合并净利` 中位、夹 `[0, 0.95]`，无可用财年取最新财年 `少数股东权益 ÷ 权益合计`；`V = EV − fin_nd − 少数股东扣减 + x`；带文件 `net_debt_ps = fin_nd + 少数股东扣减 − x`，另落 `fin_net_debt_ps`／`minority_book_ps`／`minority_share`／`minority_share_basis`；薄权益守卫的放大倍数只按不随 EV 缩放的扣减计（`fin_nd`，账面下界生效时再加账面额）；§6.4 叠加重算 `IV = (EV × scale − fin_nd) − max(账面, m × (EV × scale − fin_nd)) + x`。权益路径 `V = V(eps0 = roe0 × BPS_op) + x`；零增长锚与敏感度带同式。§6.8 海外链同式，`m` 取 `少数股东权益 ÷ 权益合计`。建带命令 `--minority-basis earnings`（缺省）；`book` 为研究开关。
4. 带文件写 `bps_operating`／`external_equity_ps`／`external_equity_cum_ps`／`shares_est`／`bps_basis_date`／`equity_anchor_mode` 列；建带结尾打印 `|x|/BPS` 分布、超过 10% 的最新带名单与各退化模式计数（§13 第 3 条）。
5. **BPS 的股本基准按数据判定**：`bps_basis_date` 由本行与上一行 BPS 之比对照送转因子按对数距离判定；回测逐日展开、生产带除权归一化、档案折算三处的**送转**窗口一律自 `bps_basis_date` 起算，**现金分红**窗口自公告日起算。

**少数股权交易的事件口径**：发现少数股权收购、回购／退出义务或对应分红远期时，在 `data/reference/minority_claim_events.json` 登记原始披露事实；按 `known_from` 取估值时已知版本，并要求快照 `report_date` 与模型报告期一致，不把签约当作交割，不向历史回填较晚披露的数值。普通非事件公司维持上述窗口法。事件公司的处理统一为：

- 同期完整股权桥快照包含股数、合并权益、债务字段合计、现金、营业收入、各项回购及分红义务、已在债务合计内的金额，以及覆盖／未覆盖的少数权益。已计金额从金融债务中移出，单独的合同现金请求权计一次；未计金额补入资本结构。流动／非流动科目迁移不改变经济扣减。
- 明确固定对价退出的权利，扣披露的回购负债现值及退出前分红现值，不再分走永续权益；仍存续的少数股权按最新同口径盈利份额与账面下界计值，其已经确认的分红请求权作为同一普通权益请求权的下界，不重复相加。无法核清覆盖关系或退出对价仍取决于未来估值时，标记 `minority_claim_blocked`、判无法估值，不假定只扣固定负债即可取得全部权益。
- 持股变化后不混用变化前的集团盈利占比：用最新完整财年的集团少数损益，减去该子公司当年披露的少数损益，再加该子公司同年利润乘当前未被固定退出覆盖的持股比例，除以同年合并利润，夹 `[0, 0.95]`；多子公司逐项合计，负利润或缺失输入判不可估。该代理值和账面下界均留痕，不把子公司持股比例直接当作集团利润比例。
- 事件期间的经营分子按合并 NOPAT 总额归一化后除以快照股数；历史分子折到同一股数，沿用增长信任、峰谷守卫、增长与折现参数。季报当期化只用合并净利 TTM／年报合并净利，禁止将买入少数股权带来的归母增厚当作合并经营增长；无合并 TTM 则使用年报锚并注明。债务与权益权重取同一快照，现金已含交割付款，不再叠加外生权益残差。需同口径完整快照而尚未补齐时判不可估。
- 候选、B2、零增长及敏感度共用 `scripts/minority_claims.py` 的股权桥；预告仅披露归母利润时不对事件带作比例叠加。新拒绝必须阻断旧带回退，档案／阅读页显示具体原因；事实更新后重算恢复，禁止手填估值带。事件表只登记财报事实和合同权利，不接受 `m`、EV、IV、估值倍数或目标价。

统一参数：折现率 `r = 10%`（统一要求回报率，不逐公司调整）；`g_T = 3%`；显式期 10 年线性 fade。护栏拒绝（亏损、`ROE_T/ROIC_T` 贴 `g_T`、零增长股权价值 ≤ 0、**薄权益**——每股净负债 ≥ 50% 每股企业价值）统一判「无法估值」（§6.5.2.4）。生产参数由 §6.7 的建带命令唯一给出，不在逐票档案临时改写。

所有正常模型带均为 `[0.90×V, 1.10×V]`，中值即 `V`；带宽只作区间展示，不代表统计置信区间。

#### 6.5.2 逐票估值档案

##### 6.5.2.1 P/V 与带宽

正常生产带的中值必须等于模型内在价值。生产 `P/V` 与回测 `valuation_ratio` 在未叠加预告的行上使用同一分母（`scripts/pv_ratio.py` 与逐日状态同式）；被 §6.4 叠加过的行是成文例外，生产分母比回测分母新。

叠加只写生产带 `a_share_pool_model_bands_adopted.csv`，**回测输入 `roic_bands.csv`／`roic_daily_raw.csv`／`a_share_daily_states_adopted.csv` 一律不碰**。带文件的 `forecast_overlay` 列非空即表示该行已叠加；引用回测读数论证生产行为时先看这一列。

##### 6.5.2.2 模型计算

模型计算统一由 §6.7 命令完成；档案不得覆盖模型参数或为希望得到的 `P/V` 反推输入。

##### 6.5.2.3 生产带落地

`data/processed/a_share_pool_model_bands_adopted.csv` 是生产模型带唯一来源，**只含池成员**（分层表 worth_attention L1-L3；池外档案的带由 `apply_model_bands_to_dossiers.py` 直接取自全市场模型带、只落档案），**其带值恒为现价口径**：§6.7 第 4 步的叠加脚本末段按除权事件（现金自带公告日起、送转自 `bps_basis_date` 起，§6.5.1 第 5 条）归一化，`exright_note` 列非空即已折算。池外原始模型带也由档案写入脚本调用相同除权实现，事件截止取信号日；池外银行与保险的利率和股利按 §11.3 的信号日口径读取。逐票档案只承载研究结论和当前带；`apply_model_bands_to_dossiers.py` 只覆盖带相关字段，保留 `key_metrics`、`review_triggers`、高频指标和研究备注。README 第八节「现价隐含了什么」的首段由 `build_company_dossier_readmes.py` 按生产带与池内现价机械生成（`现价 ÷ 中值 = P/V`、路径与增长/折现假设、归一化盈利倍数），`implied_growth_years` 的新增研究只记录可证伪命题与方法分歧；已有原文在折叠区标明证据须复核，不作为当前估值或交易依据。带变更历史留在 CSV 的 `notes`，不重复铺陈于 README；页面分别标注估值更新日与质量证据日。

**持仓侧带** `data/processed/a_share_pool_model_bands_hold.csv`：§6.7 第 4 步由候选侧生产带与 B2 池带（§6.5.1 B2 口径）逐票取 `intrinsic_value` 较高的一行，两侧各自完成预告叠加与除权归一化后再取，`hold_source` 列标明来源；成员与候选侧生产带相同。§9.3.1 换仓来源读持仓侧带；买入线、候选排序、档案、阅读版与 §6 其余判定只读候选侧生产带。回测同构：候选侧读 `a_share_daily_states_adopted.csv`，持仓侧读 `a_share_daily_states_hold.csv`（§6.7 第 3 步逐 (代码, 日期) 取较高 V，`--hold-states`）。

生产 `P/V` 与回测 `valuation_ratio` 必须逐位一致（§6.4 叠加行除外）。**晚间披露报告的当晚吸收两侧同构**：生产在公告日戳的前一晚即用新带出信号；回测逐日状态里每条带自**可得日之前的最后一个市场交易日**起生效（`build_historical_valuation_bands.py --state-effective prev_trading_day`，缺省；前一交易日按上证指数日历取，行情库在该公告前已断的陈旧序列退回可得日生效）。带的可得日按 §6.3 第 2 条封顶（`--notice-cap statutory`，缺省）。回测的均线与建仓止损锚同样与实盘同构：均线按前复权口径折回当日股本／分红基准（§8.3），除权日止损锚与持有期峰价按 §11.4 同式折算（§9.3.5）。早于 §6.5.2.4 时点门槛的陈旧模型带不进任何一层：扫描器无 `P/V`、档案层判「无法估值」，两层同一结论。

##### 6.5.2.4 主体重置与无法估值

**主体重置**（重组、资产注入、并表或借壳使旧财务主体不可比）：在 `data/processed/entity_reset_dates.csv` 登记 `security_code,security_name,reset_report_date,growth_mode,known_from,reviewed_at,note`；`reset_report_date` 取新主体首个年报期末，`growth_mode` 取 `none`（不增长）或 `trend`（按季报趋势给增长），`known_from` 取重置后首份定期报告的可得日（可得日早于它的带不施加重置；留空即一律施加）。**触发**：§6.7 第 5.5 步检查⑦「股本事件复核」报出核心池内近 3 年非送转、单次变动 ≥ 5% 的股本事件（读 `data/raw/share_changes/a_share_share_changes.csv`）；逐条核对公告后登记 `data/processed/share_event_reviews.csv`（`security_code,security_name,effective_date,change_reason,decision,reviewed_at,note`，`decision` 取 `reset`／`no_reset`），判 `reset` 者同时登记本名册；已登记的事件不再报出。§6.7 第 2 步自动读取该表：报告期 ≥ 重置日的行把比率窗口、十年守卫窗口与经营账面基年截到重置日起；重置后不足三个年报时，锚 = 最新年报比率 × TTM 因子，`none` 时 `g0 = 0`，`trend` 时 `g0 = min((TTM 因子 − 1) × 增速腿权重, g0 上限)`（TTM 因子 < 1 + `--ttm-trust-delta` 时为 0）；上年同期行早于重置日时由本行 `netprofit_yoy` 反推同期数。重置后满三个年报即回到通用路径，无需人工动作；早于重置日的行不受影响。

**购买法收购当年分子年化**：非同一控制下企业合并的收购当年，在 `data/reference/consolidation_events.csv` 登记 `security_code,security_name,acquiree,acquisition_date,report_period,months_consolidated,acquiree_revenue_since,acquiree_net_profit_since,source,reviewed_at,note`：`report_period` 取收购当年年报期末，`months_consolidated` 取购买日至期末的并表月数（留空按购买日算，15 日前含当月；全年并表者不登记），两项贡献取该年报「企业合并」附注「被购买方自购买日至期末的收入／净利润」（元）。§6.7 第 2 步读取该表：该年报期的 NOPAT 与 EBIT 各加 `净利润贡献 × (12 ÷ 并表月数 − 1)`，权益、股本、现金流与归母／合并净利不动。**登记触发**：检查⑦报出的发股收购经核对为非同一控制下合并者，以及用户点名的现金收购；同一控制下合并不登记。

**无法估值**：亏损、归一化 ROE 非正、`ROE_T` 贴近 `g_T`、零增长股权价值 ≤ 0、薄权益、最新 ok 模型带早于 `2025-01-01` 时点门槛——一律判「无法估值」：档案带清空、池内可见、带显示 —、无 `P/V`、不进 §9.3 任何判定；模型重新可算后自动回归模型带。不设手工带。

#### 6.5.3 估值质量分与敏感度带（输出列，不进任何判定）

建带命令对每条 ok 带另写四列，**只用于读带时判断参数敏感度与输入可信度，不进入 §9.3 任何买卖判定，也不改带值**：

| 列 | 定义 |
| --- | --- |
| `valuation_quality_score`（0-100） | 五个分项各 20 分相加：①历史长度（可用财年 ≥8 → 20；5~7 → 12；≤4 → 5）；②回报稳定性（逐年 ROIC／ROE 的变异系数 ≤0.25 → 20；≤0.50 → 12；其余或不可算 → 5）；③终值占比（≤0.60 → 20；≤0.75 → 12；其余 → 5）；④路径与守卫（growth 未触 peak 守卫 → 20；growth 触守卫或 zero_growth → 10；equity_fallback → 5）；⑤两腿一致度（g 的资本腿与增速腿、权益口径的 g_sustainable 与 g_trailing：两腿可算且差 ≤5pp → 20；≤10pp → 12；只有一腿 → 12；差 >10pp 或皆无 → 5）。`valuation_quality_notes` 记各分项得分 |
| `v_bear` / `v_bull` | 同一引擎、五个参数同向扰动后的每股价值：Bear = g0×0.5、折现率 +1pp、终值回报 −1pp、fade 7 年、g_T −0.5pp；Bull = g0×1.25（受 g0 上限）、折现率 −1pp、终值回报 +1pp（不高于起点回报）、fade 13 年、g_T +0.5pp；zero_growth 只扰折现率 ±1pp；银行与保险（股利折现覆盖）不算。任一侧触护栏即留空。**Bull 不给交易层用**，带宽仍是 §6.5.1 的 ±10% |

建带结尾另按「每只最新 ok 带」打印路径分布（只数、市值占比、前三行业）。

#### 6.5.4 维持性现金占用研究开关

`build_historical_valuation_bands.py --maintenance-weight` 缺省 0；非零只用于实验目录中的 ROIC 带，并须使用非 `legacy` 的营运资金口径（生产 `operating`；`reported` 只复现上轮研究）。代理估计、现金流衔接、缺失处理与测试设计统一读取 `data/experiments/exp_maintenance_cash_20260909/preregister.md`。候选侧、B2 与敏感度计算使用同一修正，金融与权益退路不应用；新增拒绝须在逐日状态生效后阻断陈旧带。按 §12 完成验证后再处理生产采纳。

### 6.6 人工复核职责

人工只处理：模型不可估原因；主体不可比（重置日与 `growth_mode`）；新证据是否触发重算；校验失败行。正常公司不逐票选择模型、倍数或带宽。

档案必须保留证据事件、证据可得日、关键指标、高频指标、下一复核点和可证伪触发。带变动后重渲染逐票 README。

### 6.7 估值重建链

以下顺序是当前唯一生产路径。重建全历史模型带属于重作业，必须独占运行。

本链需要日期的 A 股命令使用 `--signal-date`；无日期参数的构建工具读取上游产物。常设作业入口 `scripts/slurm/rebuild_chain_with_fetch.sbatch`（`SIGNAL_DATE`、`SINCE`，可选 `EXTRA_CODES` 点名补取三大报表）串行执行第 1 步六份取数、第 2／2b 步两侧建带与第 3 步银行保险覆盖及持仓侧逐日状态合成；第 4 步起按下文命令执行。证据日由 `scripts/a_share_signal_dates.py` 唯一推导为信号日之后的首个工作日（周一至周五）；调用方不得另行指定证据日。

```bash
# 1. 刷新财务输入与除权事件（逐季财务、三大报表、除权事件、rf/ERP 序列、股本变动事件、股债利差六份缺一不可）
python3 scripts/fetch_a_share_quarterly_financials.py --signal-date YYYY-MM-DD --since <当前报告期末>
python3 scripts/fetch_a_share_financial_statements.py --signal-date YYYY-MM-DD
python3 scripts/fetch_ohlcv_history.py --signal-date YYYY-MM-DD --actions-only
python3 scripts/fetch_cost_of_equity_inputs.py   # rf/ERP 序列：银行/保险股利折现（第 3 步、扫描器 --rf 缺省、档案层）与 §6.8 的 r 读它的最新行
python3 scripts/fetch_a_share_share_changes.py --signal-date YYYY-MM-DD   # 股本变动事件表（第 5.5 步检查⑦读它）
python3 scripts/fetch_equity_bond_inputs.py --refresh   # 沪深 300 TTM PE 与 10 年国债：§9.3.1 股债总仓位上限读不晚于信号日的最新观测（过期门槛见该行）

# 2. 构建 ROIC 带与逐日状态
python3 scripts/build_historical_valuation_bands.py --all --value-model roic \
  --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
  --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings --wc-aggregation operating \
  --out-bands data/processed/roic_bands.csv \
  --out-daily data/processed/roic_daily_raw.csv
# 2b. B2 带与逐日状态（持仓侧第二输入；与第 2 步串行、不得并发）
python3 scripts/build_historical_valuation_bands.py --all --value-model roic \
  --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
  --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings --wc-aggregation operating \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands data/processed/roic_bands_b2.csv \
  --out-daily data/processed/roic_daily_raw_b2.csv

# 3. 银行与保险改用股利折现并生成采纳逐日状态（保险名单在 scripts/divspread_names.py），两侧各一份，再合成持仓侧逐日状态
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_adopted.csv \
  data/processed/roic_daily_raw.csv \
  data/processed/roic_bands.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_b2.csv \
  data/processed/roic_daily_raw_b2.csv \
  data/processed/roic_bands_b2.csv
python3 scripts/build_hold_daily_states.py   # 持仓侧逐日状态 = 逐 (代码, 日期) 取两侧较高 V → a_share_daily_states_hold.csv

# 4. 生成池模型带 → 叠加预告/快报 →（B2 池带同两步 → 持仓侧池带）→ 写入逐票档案
python3 scripts/build_pool_model_bands.py --signal-date YYYY-MM-DD
python3 scripts/apply_forecast_band_overlay.py --signal-date YYYY-MM-DD
python3 scripts/build_pool_model_bands.py --signal-date YYYY-MM-DD \
  --bands data/processed/roic_bands_b2.csv --states data/processed/a_share_daily_states_b2.csv \
  --out data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date YYYY-MM-DD --bands data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py --signal-date YYYY-MM-DD   # 持仓侧池带 = 逐票取候选侧与 B2 较高 V → a_share_pool_model_bands_hold.csv
python3 scripts/apply_model_bands_to_dossiers.py --signal-date YYYY-MM-DD

# 5. 档案 → 建带卡 → 估值表
python3 scripts/build_valuation_band_cards.py \
  --tags data/interim/strategy_tag_map.csv \
  --out data/interim/valuation_band_cards.csv \
  --signal-date YYYY-MM-DD
python3 scripts/apply_valuation_band_cards.py --signal-date YYYY-MM-DD --quotes fetch

# 5.5 逐行自洽核对财务面板
python3 scripts/audit_financial_panel_consistency.py --signal-date YYYY-MM-DD

# 6. 校验并物化核心池
python3 scripts/validate_valuation_bands.py \
  --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv \
  --queue-out data/interim/valuation_rebuild_queue.csv \
  --signal-date YYYY-MM-DD
python3 scripts/build_a_share_core_valuation_pool.py --signal-date YYYY-MM-DD   # 物化后自动渲染公司 README
python3 scripts/build_company_dossier_readmes.py --check

# 7. 换仓边际的标度漂移守卫（两套逐日状态重建后必跑）
python3 scripts/check_swap_margin_scale_drift.py
```

第 1 步不得跳过；披露窗未关的报告期由脚本强制重取并在结尾告警，除权事件库随第 1 步同批刷新。

公司 README 的价格为核心池 CSV 的估值物化快照，明确显示价格日期；每日执行价只读 §8 的已发布行情。README 在核心池物化后渲染；仅刷新阅读版行情不改变该快照。自动渲染不得改写人工研究证据日期。

第 1 步结束后 `data/interim/statement_coverage_gaps.csv` 须为空；有行即先补取三大报表，补不到的登记 `docs/000_Ashare_workflow_open_issues.md` 后再继续。第 2 步结尾的 `data/interim/valuation_statement_gaps.csv` 同此，其中的代码在第 6 步判 blocking、冻结新增买入。

第 7 步退出码非 0 时按 §12 重扫 §9.3.1 换仓边际，再把 `check_swap_margin_scale_drift.py` 的基准重定到新值；未重扫前不得据该判据下换仓结论。

第 5.5 步只报异常不改数，**「严重」级须逐条处置后才继续**。任一步失败即停止；不得把旧估值表上的校验通过当成新带已生效。完成后核对模型带、档案、估值表和核心池的带值与日期一致，持仓侧带的成员与候选侧生产带一致。校验失败行冻结新增买入，修复后再物化。

仅刷新每日现价时运行：

```bash
python3 scripts/build_a_share_core_valuation_pool.py \
  --md-only --quotes fetch --signal-date YYYY-MM-DD
```

### 6.8 海外关注清单

港股、美股和韩股只作为观察附表，不写入 A 股核心池，也不进入 §9.3。质量判断沿用 §5，估值遵守价格独立、证据改带和可证伪原则；交易货币不得跨市场直接比较（`P/V` 可以）。

**输入符号与拒绝传播**：SEC 的纯利息费用标签按每个年度／累计期间的费用金额正值统一，再合成 TTM；不得对合成结果取绝对值代替逐期统一，所得税收益及其他有经济含义的正负值保留。零增长与增长路径均在各自企业价值的股权桥之后执行 §6.5.1 薄权益守卫，固定扣减按该节的净金融负债与少数股东账面下界口径计算；拒绝后清空当前带、合理价和 P/V，档案显示原因，不回退历史带。

**海外估值**：合理估值按 §6.5.1 的 ROIC 引擎由三大报表重算，海外输入与折现率按本节处理，最新季报／中报按「最近完整财年＋本期累计−上年同期累计」合成 TTM 作为当前观察点，年度历史仍用于 ROIC0、增量 ROIC 与再投资率。r = 美债 10Y ＋ β×经营地 Damodaran ERP（β 与终值超额回报分别读取海外引擎 `BETA_BY_TIER`、`TERMINAL_EXCESS_BY_TIER`，无质量档者按名单状态读取；终值增长受 `terminal_growth_ceiling` 约束），报表币按 `data/reference/overseas_valuation_inputs.csv` 的汇率折到交易币、ADR 按普通股数折算；金融企业（`FINANCIAL_KEEP`）ROIC 不适用，沿用档案带并标明；ROIC 路径被拒或无三表源（韩股、未申报公司）一律「无法估值」。三表来源：美股 SEC XBRL companyfacts（标签按经济含义组合，唯一实现 `fetch_overseas_statements.compose_sum`／`compose_debt`：合并税前利润取合并标签，缺则境内＋境外、再缺持续经营净利＋所得税，不得由境内单项兜底；有息负债 = 非流动长期债务／票据 + 流动债务（`DebtCurrent` 存在即整体取用）+ 融资租赁负债，同一层级只取一次、含租赁标签不再叠加租赁、经营租赁不计；折旧摊销取合计标签，缺则折旧＋无形资产摊销；年报与季报 TTM 同规，`tags_used` 记所用组合）、港股东财 HK F10；SEC 结构化事实尚未覆盖的已披露季报（包括境外发行人 6-K 和 10-Q 提交前的官方业绩三表）按官方财报维护 `data/reference/overseas_statement_overrides.csv`（原始文件不入库，提取结果 `data/interim/overseas_roic_years.csv` 入库）。

```bash
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --apply
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --check-only
python3 scripts/fetch_overseas_statements.py --as-of YYYY-MM-DD [--refresh] # 年报＋最新季报 TTM → overseas_roic_years.csv
python3 scripts/build_overseas_roic_bands.py --as-of YYYY-MM-DD            # ROIC 口径合理估值 → overseas_watchlist_valuation.csv ＋ README「当前估值」节
python3 scripts/build_a_share_core_valuation_pool.py --md-only --quotes fetch --signal-date YYYY-MM-DD
```

阅读版 `000_a_share_core_valuation_pool.md` 两表列：代码／名称／质量／参考分／估值／估值路径／现价／**合理估值 V**／**`P/V`**／估值时间／估值事件（合理价区间、空间、策略标签、PE、PB 只在 CSV）。表前只保留字段含义与交易边界；估值路径只显示方法名，不带章节号或口径注记。

**回购与分红的处理**：估值只看「可分配现金 = NOPAT × (1 − 维持增长所需留存)」，分红与回购同属可分配现金、不区分、不另按股数缩减重复计量，未来回购计划不进模型。海外引擎的锚按以下口径计算：年报间外生权益按股本口径第 2 条逐年识别（`X_y = ΔE − (归母综合收益 − 已付股息)`，综合收益缺失用归母净利，已付股息取现金流量表；权益缺失的年份不计、不作断点），比率 = 各年 NOPAT ÷ 当年经营账面 `E_op`，季报观察点当期 = 最新年报比率 × (NOPAT TTM ÷ 最新年报 NOPAT)，λ 与三年／五年／十年中位只取年报，周期守卫坡道与谷底守卫同式；每股 NOPAT 锚 = ratio0 × 经营账面 `BPS_op = 当期 BPS − x − X_cum/股`，`x = 当期 BPS − (最新年报母公司权益 + 其后归母净利 − 其后已付股息) ÷ 申报稀释股数`（年报行 `x = 0`；`x` 封顶 95% BPS；其后归母净利或已付股息不可得时 `x = 0`）；净负债与少数股东取季报资产负债表，`x` 不另进股权桥；增速腿权重 0。`overseas_statement_overrides.csv` 维护行的 `net_income`／`tci`（年报行）与 `net_income_ytd`／`dividends_paid_ytd`（TTM 行）留空时，取数脚本按东财 `RPT_USF10_FN_INCOME`／`RPT_USF10_INFO_DIVIDEND` 补入；港股现金流量表缺「已付股息」行时按 `RPT_HKF10_INFO_DIVIDEND` 分红事件补入（除净日落在期内，每股派 × 最新已发行股数，按 `overseas_valuation_inputs.csv` 汇率折报表币）；补缺来源写入 `tags_used`。A 股分红按 §11.4 除权归一化处理，银行股利折现只计现金股利。

**点名建档**：用户点名的港股／美股／韩股公司，无论初筛结论如何，一律完成以下六步：

1. 写逐票档案 `data/companies/<代码>_<名称>/README.md`（质量档、四维分与旗标、合理价区间与方法、参考分理由、跟踪指标、复核触发）。
2. `data/processed/overseas_watchlist_valuation.csv` 加一行：登记 `attention_class`，`quality_tier` 按 §5.7 定档；`boundary_pending` 与 `garbage` 的档位和分数留空，`buy_eligibility` 恒为 `off_pipeline_watch_only`，`dossier_dir` 指向第 1 步目录。
3. `data/reference/overseas_report_evidence.csv` 加最新定期报告的证据行。
4. 港股在 `fetch_overseas_statements.py` 的 `HK_REPORT_CCY` 与 `build_overseas_roic_bands.py` 的 `COMPANY_CFG` 登记；银行／保险／金融控股进 `FINANCIAL_KEEP`，带取档案带。
5. 依次运行本节命令并重出阅读版；三表取数不可得时 `build_overseas_roic_bands.py` 判「无法估值」。
6. 按 §2 写决策日志。

阅读版海外附表列出清单 CSV 的全部行。`build_a_share_core_valuation_pool.py --md-only` 每次建表核对 `data/companies/` 下每个档案目录都登记在 `a_share_valuation_dossiers.csv` 或本清单，未登记的写 `data/interim/dossier_registration_gaps.csv` 并非零退出；补登记后重跑。

海外最新定期报告只认 `data/reference/overseas_report_evidence.csv` 的公司 IR／交易所／监管申报证据。附表 `估值时间`、清单 `valuation_reviewed_at`／`evidence_available_at`／`last_report_date` 均写该报告的公开可得日，`估值事件` 写报告类型；不得写脚本运行日。`next_report_date` 只作预期提醒，过期日历日期未获官方证据确认时不得当作已披露，且必须报“待核验”并核对公司官方业绩页。报告日、证据日、带和不可买状态维护在 `data/processed/overseas_watchlist_valuation.csv`。

## 7. 阶段三：披露与事件滚动更新

### 7.1 证据同步与更新队列

先刷新队列读取的两个证据源：

```bash
python3 scripts/fetch_a_share_report_disclosures.py --signal-date YYYY-MM-DD --report-date <当前报告期末> \
  --output data/interim/a_share_report_disclosures.csv
python3 scripts/fetch_a_share_earnings_forecasts.py --signal-date YYYY-MM-DD --report-date <当前报告期末> \
  --output data/interim/a_share_earnings_forecasts.csv
```

再重建队列：

```bash
python3 scripts/build_report_update_queue.py \
  --market A_SHARE \
  --signal-date YYYY-MM-DD \
  --attention-triage data/processed/a_share_attention_triage.csv \
  --tiers data/processed/a_share_watchlist_quality_tiers.csv \
  --valuation-pool data/processed/a_share_core_valuation_pool.csv \
  --forecasts data/interim/a_share_earnings_forecasts.csv \
  --report-disclosures data/interim/a_share_report_disclosures.csv \
  --output data/interim/a_share_report_update_queue.csv
```

**三个文件都必须当日重建**；任一文件日期早于扫描日即不可用。`garbage` 不进入队列。队列只纳入公告日不晚于信号日自动推导的证据日的预告、快报与定期报告。

`<当前报告期末>` 取最近一个已开始披露的报告期末（`2026-06-30` 一类）；披露窗未关时（法定截止日：一季报 4-30、半年报 8-31、三季报 10-31、年报次年 4-30）每日重取。

### 7.2 质量复核触发

```text
quality_cutoff = max(last_quality_review_date, evidence_available_at)
定期报告公告日 > quality_cutoff → 进入质量复核
```

披露文件缺失时才以报告期末作降级兜底，并在队列显式标注。

### 7.3 估值复核触发

预告、快报或正式定期报告的公告日晚于 `max(valuation_reviewed_at, evidence_available_at)`，即进入估值复核，不先判断幅度是否重大。披露文件缺失时才用报告期末兜底。

`valuation_reviewed_at` 取生产带文件 `model_evaluated_at`（模型最近评估过的报告期可得日，含护栏拒绝行）与采纳带可得日的较大者；`evidence_available_at` 取采纳带可得日。

### 7.4 事件复核触发

以下事件当天复核：披露；重大订单或客户认证；产品与技术兑现；并购、资产出售或控制权变化；问询、处罚或审计异常；产业政策、商品价格或竞争格局重大变化；档案列明的高频指标越过触发线。

每天必查范围：全部持仓、当日披露触发、当日通过买入线与走势条件的股票、用户点名股票。若未覆盖完整范围，必须报告实际覆盖度。

处理顺序：先更新档案证据与关键指标，再重算模型带，再完成 §6.7 下游落地与校验。重新取证后带变动不超过 2% 时只刷新证据日；超过 2% 时同时更新估值复核日与证据事件。

### 7.5 复核期冻结

估值或事件复核触发后，将 `buy_blocked` 设为 `review_pending`，冻结新增买入但继续持仓跟踪。完成复核、更新证据与复核日期并重建队列后自动解除。

**预告与快报触发的估值复核由 §6.4 的叠加机械完成**：叠加把带与 `valuation_reviewed_at` 一并推进到公告日，队列重建后冻结自动解除。叠加覆盖不到的行（银行与保险、`zero_growth` 路径输入不全、股本多期倒推不一致；脚本逐行打印跳过原因）走人工复核。

**正式定期报告不过夜**：扫描当晚发现新披露即当晚以信号日跑完 §6.7 全链并重建队列，当日信号直接使用新带；链跑完仍吸收不了的行按上段走人工复核。

#### 7.5.1 Express 复核

只有 §6.4 叠加跳过的行需要人工 express 复核，原则上在下一交易日开盘前完成；发现超期时当场补做并记录原因。

#### 7.5.2 财报日价格背离

披露后首个交易日若相对披露前收盘绝对涨跌至少 7%，且到当前带的距离扩大，则持仓与当日可买股票必须在 T+1 内强制复带：

```bash
python3 scripts/check_report_day_price_divergence.py --as-of YYYY-MM-DD
```

## 8. 阶段四：每日行情取数

### 8.1 执行频率

每个 A 股交易日收盘后执行一次。

### 8.2 执行入口

```bash
python3 scripts/screen_daily_volume_price_signals.py --as-of YYYY-MM-DD \
  --review-queue data/interim/a_share_report_update_queue.csv \
  --model-bands data/processed/a_share_pool_model_bands_adopted.csv \
  --hold-bands data/processed/a_share_pool_model_bands_hold.csv \
  --nav <当日净资产> \
  --funds <现金加可用授信> \
  --cash <当日现金> --debt <融资负债>   # §9.3.1 股债总仓位上限受限期间用，未给时读账户快照台账
```

`--nav` 决定一档；`--funds` 决定当天实际可执行预算，执行模式两者必填。不给 `--nav` 时只写 `daily_quote_preview.csv` 行情预览，不发布执行计划。产物：`daily_buy_candidates.csv`（行情、候选侧 `model_pv` 与持仓侧 `hold_pv`）、`daily_sell_plan.csv`（§9.3.2 第 4 步卖出清单）、`daily_entry_plan.csv`（第 5 步买入清单）、`daily_cooldown_state.csv`（§9.3.3 计数器）。持仓不在核心池内的票由扫描器另取行情（交易所按证券名单），只进卖出侧。`--as-of` 是信号日（最近收盘日）；模型带的证据截止由同一信号日自动推导。

### 8.3 必需量

| 量 | 口径 |
| --- | --- |
| 收盘 | T 日收盘，不存在盘中版本 |
| MA20、MA60 | 前复权收盘简单移动平均（回测 `adjusted_moving_averages` 同基：按除权事件折回当日口径） |
| `P/V` | 未复权现价 ÷ §6.5 当前生产带中值；候选侧读生产带、持仓侧读持仓侧带（§6.5.2.3），两侧各列 |
| 相关性 | 日收益率皮尔逊相关，窗口与最少重叠数见 §9.3.1 相关性行；只对合格候选、在手持仓和已选候选按需计算 |

除上表判定所需量外不再计算或展示其他量价指标。

只有原始报价日期等于信号日的有效收盘可用于当日交易。均线从未复权历史按完整公司行动折到信号日口径；不得把旧前复权尾根与新未复权报价拼接，也不得在复权取数失败时降级为未复权均线。没有当日报价的持仓以已核验历史收盘经期间公司行动折算后的标记价格计市值，另列标价日期与不可交易状态；无法确定标记市值时停止新增买入及依赖总仓位的减仓计算，保留明确可判的卖出复核行。

日线取数只有一份实现（`screen_daily_volume_price_signals.fetch_daily_rows`：东财主源、腾讯备源、北交所走腾讯）；§11.3 持仓跟踪的收盘与 MA60 同用它取数。

均线、跨日价格和成交量折算须遍历完整除权事件日历，纳入两次报价之间的全部事件，不能要求除权日存在该股票报价。历史价到T日的折算窗口为 `(历史报价日, T]`，T之后事件不影响截至T的结果；停牌日不新增均线样本。相邻报价的含权收益按期间事件先后承接现金、送转和配股，停牌期现金在下一可得收盘价再投；不能在无报价日虚构再投价格。实现与边界核验见 `backtest_valuation_strategy.exright_affine`、`quote_action_factors` 和 `test_suspended_actions.py`。

证券代码变更（同一上市主体换码）登记在 `data/reference/a_share_code_succession.csv`（旧码、新码、旧码末个交易日、新码首个交易日），唯一实现 `scripts/code_succession.py`：除权事件取数每次落盘前把新码名下不晚于旧码末个交易日的事件复制到旧码，旧码已有行不覆盖（`--apply-actions` 离线补写既有事件表）；时点面板装配校验旧码区间 `effective_to` 不晚于旧码末个交易日、新码区间 `effective_from` 不早于新码首个交易日，违反即装配失败，须先在判定源对同一主体给出一致处置。新增换码对后按 §6.7 第 2～3 步以 `--codes` 重建旧码两侧逐日状态并拼回，再按 §12.1 轨道 A 复核 `BASE`。

### 8.4 故障与缺口

`--since auto` 自动检出上次扫描日（读上一份 `daily_buy_candidates.csv` 的 `trade_date`），报告缺口区间的交易日数、区间涨跌与最大放量倍数。扫描为零行或行情失败达到一半时非零退出，当日结果不可用；低于一半按停牌或个别数据缺失逐行标注。扫描写入决策日志的只有结论行：取数异常（`data_error`／`insufficient_price_history`）与 §7.5 复核冻结（`review_frozen`）；正常行情行不写。

## 9. 每日执行与交易规则

### 9.1 六步定序

信号口径与执行时点只认 §9.3.1。执行日价格变化不重算信号日合格集；停牌或执行日新增 §7 事件时跳过该票并重新复核。

1. **同步证据**：按 **§7.1** 取披露、预告并重建队列；刷新公司行动，抓取上次成功扫描以来的公告与市场背景，核查 §7.4 的每日范围。用下列 evidence 阶段生成同日完成凭据；只重建队列不算同步证据。
2. **更新估值**：队列出现 `valuation_review_needed` 时**当晚以同一信号日执行 §6.7**（含其第 1 步的逐季财务刷新）；随后重建队列，再刷新核心池阅读版。
3. **公司行动与输入核验**：先按 §11.4 处理持仓除权除息并登记台账；完成同日证据阶段证明，再校验队列、分层、持仓、三类表、两侧模型带及账户输入。空持仓可接受，文件缺失不可接受。队列即使为空也须有当日生成凭据；账户现金和负债须来自信号日快照或当日显式输入。
4. **暂存行情与事件复核**：取当日行情、计算两侧 P/V，以本次行情形成的合格集和持仓做 §7.5.2 复核；复核完成前不发布执行清单，也不回写冷却。随后跟踪持仓。
5. **校验并发布执行清单**：按 §9.3.2 先卖后买生成买卖计划；整批校验通过后发布行情、清单、冷却及含日期和文件摘要的成功凭据。缺失或摘要不符的成功凭据表示计划不可用。失败返回非零，不推进冷却；四张表即使为空也必须显示。止损行只列候选，T+1 尾盘复核后执行，其卖出款不计入当日买入预算。
6. **输出与留痕**：回复用户，并将同一内容置顶写入 `docs/000_daily_scan_log.md`；成交后按 §11.5 回写。每月首个扫描日运行 `python3 scripts/archive_daily_scan_log.py --before <本月 1 日> --apply`，把信号日早于本月 1 日的条目移入 `data/archive/daily_scan_log_<起>_to_<止>.md`（并入既有归档加 `--into <文件>`）。

当日无估值更新时可以省略 §6.7 重建，但必须明确写“当日无估值更新”。队列行 `as_of` 为信号日推导的证据截止，旁置 `.meta.json` 的 `as_of` 为信号日；凭据同时校验输入摘要。估值链改变事件文件后须重新完成 evidence 凭据；新增池或持仓代码未在公告取证范围内时重新取证。

常设调度入口为 `scripts/slurm/daily_postclose.sbatch`，四个阶段按 `SCAN_STAGE` 选择，逐日不另建包装脚本：`evidence` 要给 `SCAN_DATE`、`SCAN_SINCE`（上次成功扫描日）、`SCAN_REPORT_DATE`，可选 `SCAN_ENTRY_CODES`（当日为零股建仓成交日的代码，写 `data/interim/daily_entry_anchors_<日期>.json` 供 §9.3.5 记锚）；`preview` 只要 `SCAN_DATE`，刷新下述两项行情输入后写 §8.2 行情预览；`events` 要给 `SCAN_DATE`、`SCAN_SINCE`，只重取公告、公司行动与市场背景并重做同日证据凭据（截止时间后补取用）；`scan` 要给 `SCAN_DATE`、`SCAN_NAV`、`SCAN_FUNDS`，现金和负债可给 `SCAN_CASH`、`SCAN_DEBT`，否则读当日账户快照。evidence 阶段依次运行 `fetch_equity_bond_inputs.py --refresh` 与 `fetch_cost_of_equity_inputs.py`（§9.3.1 股债总仓位上限与扫描器 `--rf` 缺省的输入）、§7.1 两个取数脚本、`fetch_ohlcv_history.py --actions-only`、`fetch_daily_market_evidence.py --as-of YYYY-MM-DD --since 上次扫描日`、`daily_execution_guard.py evidence --as-of YYYY-MM-DD --since 上次扫描日`、队列重建；随后完成必要的模型与公司行动回写再运行 scan。

使用执行计划前运行 `python3 scripts/daily_execution_guard.py verify --as-of YYYY-MM-DD`；成功凭据必须与行情、买卖计划、跟踪表、冷却、日志和输入摘要一致，且账户快照到信号日为止的 §10.3 策略列已登记并与重算一致（缺行、空列或不一致即失败）。扫描采用同一发布锁；暂存或失败批次不可执行，中断安装会在下次扫描读取冷却前恢复。

### 9.2 输出格式

```text
## 每日扫描 YYYY-MM-DD（信号日；执行时点见 §9.3.1）

### 一、当前持仓
| 名称 | 层级 | 参考分 | 收盘 | 合理价区间 | 空间 | P/V | 动作 |

### 二、执行清单（时点见 §9.3.1）
1. 一档金额
2. 合格集及相关性
3. 卖出清单
4. 买入清单

### 三、P/V 前十（不筛走势）
| 排名 | 代码 | 名称 | 层级 | 收盘 | 合理价 V | P/V | 走势条件 |

### 四、需人工处理
除权除息、待复核、停牌、执行日新增事件和数据缺失
```

P/V 前十从当日扫描的 `worth_attention` 中，按候选侧 `model_pv` 升序取十只，同值按代码升序；仅纳入报价日等于信号日、收盘与 P/V 均为有限正数的行。排名不应用买入线、走势、复核冻结、L3 战术闸门、冷却或账户资金限制，仅作观察名单，不产生买卖动作。走势列按 §9.3.1 区分已有持仓与新建仓，标注达标、未达标或数据不足；均线不足但当日收盘与 P/V 有效的仍可入榜。少于十只有效值时列全部并注明数量，无有效值时显式报空。正式扫描与行情预览均输出该表，用户回复及每日阅读日志同步保留。

合格集为空时写“今日无合格标的，持币”，不得放宽阈值或用盘面事实补位。

### 9.3 唯一交易口径

输入边界：名单只来自 §5，合理价只来自 §6，行情只来自 §8。账户级只剩个人投资体系 §4 的两条外生硬约束，不在本节重复。

#### 9.3.1 当前参数

| 项 | 当前唯一取值 |
| --- | --- |
| 候选池 | 当日 `worth_attention` |
| 估值 | 候选侧（买入线、排序、换仓触发候选）读 §6.5 当前生产模型带；持仓侧（换仓来源）读 §6.5.2.3 持仓侧带；`P/V = 收盘 ÷ V` |
| 买入线 | `P/V ≤ 1.0454` |
| 新建仓走势 | T 日 `收盘 > MA20 > MA60` |
| 已有持仓加仓走势 | `MA20 > MA60`，不要求收盘高于 MA20 |
| 排序 | `P/V` 升序，资金用尽即停 |
| 相关性 | 只计算并在报告列出与在手及已选标的近 252 日相关性，不作过滤。两侧同取扫描当日前复权K线、按交易日对齐；重叠收益率不足 120 个时无值，报告列名单 |
| L3 战术闸门 | `quality_tier = L3` 且分层表 `tactical_thesis` 为空或判「无／暂无／不可买」者不进合格集（新建仓与加仓同，持仓照常跟踪与卖出）；战术理由的判据、里程碑写法见 `docs/Ashare_quality_rubric.md` §8，补判为条件式后自动重入。回测不复现（成文差异） |
| 单次买入 | 当日净资产 `N × 5.0%` |
| 持仓只数上限 | 无 |
| 单票机械上限 | 单票市值 ÷ 当日净资产 `N` ≥ 60% 时不再加仓；不足 60% 时本档只补到 60%（可小于一档，按一手向下取整，不足一手跳过）。**只挡加仓，不触发任何卖出**：已有持仓因上涨越限不回削，涨幅减持／换仓／止损各按本表规则；新建仓（一档 5%）与换仓目标（必为未持仓票）不受影响。按信号日收盘市值与当日 `N` 判 |
| 股债总仓位上限 | 沪深 300 股债利差（`1/PE_TTM − 10 年国债收益率`，信号日已知的最新观测）`< 3%` 时触发总仓位（持仓市值 ÷ 当日净资产 `N`）上限 `30%`；触发后须 `≥ 3.5%` 才解除，处于 `[3%, 3.5%)` 时沿用上一状态，已解除时仅跌破触发线才重新受限。状态从全部可得观测按日期重建，不随扫描重启或回测起点重置；序列开始前不施加上限。受限期间不新增融资、现金与卖出款先偿还融资负债；常规卖出后仍超限则按可交易持仓市值比例减仓至上限内（按手向上取整，停牌者延后），每笔买入以买后总仓位 ≤ 上限为限。解除后恢复本表原融资与买入规则，不强制补仓、不额外设总仓位上限。数据 `data/reference/equity_bond_csi300.csv`，观测过期超过 45 天报错不放行；当日报告同时列触发线、恢复线和当前状态 |
| 涨幅减持 | 收盘较持仓均价涨幅 `≥ 110%`（收盘 ≥ 均价 × 2.10），减一档，不看走势；持仓均价 = 买入按股数加权、减持不变、除权按 §11.4 折算（持仓表 `cost_basis`） |
| 换仓 | 只由**未持仓**的合格候选触发（已持仓候选加仓不触发），按 `P/V` 升序逐个判：可用资金不足一档时先换出**满足涨幅减持条件**的持仓一档（涨幅最大者，不比 `P/V` 边际、不要求弱势）；否则该候选（候选侧 `P/V`）须比最贵的弱势持仓（持仓侧 `P/V`）至少低 `0.15`，且被换出持仓 `收盘 < MA20`；卖一档、买一档；当日已涨幅减持的持仓不作卖出源，同一持仓每日合计至多减一档。卖出款不定向给触发候选，与其它可用资金一并按 §9.3.2 第 5 步 `P/V` 升序买入 |
| 止损 | 锚 = 零股建仓时的成交日 MA60；**生效止损线 = min(锚, 当日 MA60)**——均线下移时跟随下移、上移不抬线；执行时点（尾盘 14:45-14:55）现价跌破当日生效线即**当日**整仓清空 |
| 止盈 | 只有本表「涨幅减持」一条按盈利触发的减仓，不另设目标价 |
| 交易单位 | A 股 100 股一手；高价股按 §9.3.3 比例冷却 |
| 执行时点 | T 日收盘信号，T+1 尾盘 14:45-14:55 执行 |

本表是全部交易阈值在文档中的唯一落点。其他章节和其他文档只引用本表，不复写数值。

##### 9.3.1.1 档位基数

`N = 总资产 − 融资负债`，以信号日收盘后的账户净资产计算，每日重算。一档比例取 §9.3.1；按一手向下取整，不为迁就整手而提高档位。可用资金（§10.2）不足一档时**买到用尽**：本档金额 = min(一档, 可用资金, 单票上限余量)，按一手向下取整；不足一手跳过。

##### 9.3.1.2 生产与回测同步

生产参数落在 `screen_daily_volume_price_signals.py` 的 `SEC93_*` 常量；回测基准落在 `sweep_backtest_configs.py` 的 `BASE`。修改 §9.3.1 时必须同步两处，并运行 `scripts/test_strategy_parameter_sync.py`。

回测新实验一律使用：

```bash
python3 scripts/sweep_backtest_configs.py <配置文件> --out <结果文件>
python3 scripts/sweep_backtest_configs.py --report --out <结果文件>
```

配置文件只写相对 `BASE` 的变化，不手抄完整基准命令。回测宇宙固定读取 `data/processed/pit_attention/panel_moat_bank_v6b.csv`，估值状态固定读取 `data/processed/a_share_daily_states_adopted.csv`（候选侧）与 `data/processed/a_share_daily_states_hold.csv`（持仓侧，`--hold-states`：换仓来源、簇内升级与 T+1 换仓确认读它）。

回测基准的融资口径：本金 300 万；授信比例与强平线同 §10.2 与个人投资体系 §4；融资年利率 3.5%；资金顺序按 §10.2（授信每日按净资产重定，所有卖出款先偿还超出额度的负债，负债回到额度内才可买入，换仓与买入按现金＋剩余授信判）。实盘与回测同口径。

回测的执行与公司行动口径：T+1 成交日无价（停牌、末日）该笔跳过、不回落信号日成交（与 §9.1 同）；除权按 §11.4 同式折算，配股全额认购、认购款不足部分计融资负债；现金红利按除权日计入现金（不模拟到账日，成文差异）；差别化股息税按卖出时持有期对所卖股份持有期内已收现金红利结算（≤1 个月 20%、≤1 年 10%、>1 年免，FIFO；送股面值部分不计，成文差异）；差异化分派按公告每股派息（成文差异）。

#### 9.3.2 每日机械顺序

1. 计算全池当日 `P/V`，排除不在名单、`review_pending`（回测不复现，成文差异）与 L3 无战术理由（§9.3.1 L3 战术闸门）股票。
2. 形成走势合格集：新建仓与加仓分别使用 §9.3.1 的条件。
3. 按 `P/V` 升序计算相关性，只列报告、不过滤。
4. 先卖：
   - 执行时点现价跌破当日生效止损线（§9.3.1 止损行）：当日整仓清空，且不再走当日其他路径。
   - 触发涨幅减持条件（§9.3.1 涨幅减持行）：减一档。
   - 已移出 `worth_attention`：每日减一档直至清空，不加走势条件。
   - 未持仓合格候选想买但资金不足且满足换仓条件（已持仓候选加仓不触发）：先按 §9.3.1 涨幅减持条件选持仓减一档，否则减持最贵的弱势持仓一档；当日已涨幅减持的持仓不作卖出源，同一持仓每日合计至多减一档，无其他卖出源即停止换仓。
   - 任何减档后的余仓不足一手时清空。
   - 股债总仓位上限（§9.3.1）受限期间：以上卖出后总仓位仍超上限，按可交易持仓市值比例减仓至上限内（按手向上取整），先于换仓与买入，卖出款先偿还融资负债。
5. 后买：对合格集按 `P/V` 升序逐个买一档（含换仓卖出款，不定向给触发候选），按手向下取整，可用资金耗尽即停；股债总仓位上限受限期间不新增融资，每笔买入以买后总仓位 ≤ 上限为限。
6. 同日对冲：同一只股票当日买卖并存时按较小者抵消，只执行净额，被抵消部分不计佣金、印花税与股息税。适用涨幅减持与换仓；出名单与止损为强制退出，不抵消，同日买入清单里出现该股即在报告显式提示。

股数以 T 日收盘估算；T+1 按实际成交价调整手数，一档金额不变。

回测买卖档位冻结为信号日净资产；成交日价格只改变手数，成交日盯市继续服务资金与风险约束。出名单的持仓不得重新进入买入或换仓触发候选；同日已减档的来源不得重复换出。零股数不算卖出，不登记换仓来源。

#### 9.3.3 高价股比例冷却

一手金额大于一档时仍可计划成交一手，**只有用户确认实际成交后才启动冷却**。令 `x = 实际净成交金额 ÷ 原信号日一档金额`，随后跳过 `max(0, round(x) − 1)` 次该票的合格机会；完整一手按实际成交价计，部分成交按实际金额计，同一计划同日的分笔成交合计后算一次；同股同侧同日的回执须归属同一原始计划，一手按成交均价计算未超过一档的不启动比例冷却。买入侧一个计数器，卖出侧（涨幅减持、出名单减持、换仓卖出）另一个计数器，两侧互不消费；止损、强平及股债强制减仓不启动本冷却。

扫描只能消费已启动的冷却，不得因生成计划、资金不足、未成交或净额对冲为零启动冷却。合格机会沿用买入合格集与卖出减档信号，每个信号日同股同侧最多消费一次；无相应信号不消费，已有冷却在一手金额降至一档以内时仍适用。冷却计数不按自然日推进。实际成交日盘后的新信号是成交后的第一次机会。

合格机会按信号日判定；T+1 无成交报价不撤销前一信号日已消费的机会。模型缺失或拒绝时两侧 P/V 均各自留空，不以展示带或另一侧模型补值；出名单只按三类表判定，核心池缺行本身不构成退出信号。

用户确认的净成交通过 §11.5 登记到 `data/processed/cooldown_executions.csv`，同一 `execution_id` 重复登记相同内容为幂等、内容冲突报错；分笔成交用不同本地记录标识，不存券商账户或成交编号。`data/processed/daily_cooldown_state.csv` 为已确认成交及合格机会派生的计数快照，扫描读入、消费并原子回写；同一信号日重跑从 `remaining_before` 重算。当天扫描后才补记当天成交的须重跑当天扫描；早于最近已扫描日的成交不得直接回写当前冷却，须先按历史输入重放受影响区间。历史扫描早于当前状态时不应用、不回写当前计数。缺少成交凭据的非零计数不得自动迁移为已确认冷却。

#### 9.3.4 现有持仓衔接

不做一次性组合重构。在名单内的持仓继续按 §9.3 加减；已出名单的逐档清仓；不因持仓只数多或被动上涨形成高权重而单独卖出。

#### 9.3.5 建仓止损的记录与复位

按 §9.3.1 的止损口径，由零股建仓时把实际成交日的止损基准（**锚**）写入 `entry_stop_price`。加仓不重设，清仓后重新建仓才重设；除权除息按 §11.4 同因子调整锚（回测 `apply_corporate_actions` 同式折算）。

**生效止损线每日取 `min(锚, 当日同周期均线)`**：锚永不上移，均线跌到锚下时生效线跟随均线；执行时点现价低于生效线时当日即清，不引入等待日。持仓表只存锚不存周期（§11.2 五列），`track_holdings_daily.py` 统一按当日 MA60（前复权口径，§8.3）计算生效线，收盘跌破时提示次日尾盘按当日线复核。锚恒为成交日 MA60；成交日取不到 MA60（停牌回落、上市不足 60 根）时锚退成交日 MA20、生效线按同周期均线判，MA20 锚持仓按同周期人工复核。

## 10. 买入过滤与账户约束

### 10.1 买入过滤器

以下任一命中即跳过并顺位补下一名：

1. 不在 `worth_attention`。
2. thesis 已证伪，或存在造假、审计、资金占用与重大治理风险。
3. `buy_blocked = review_pending`。

第 3 项只挡新增买入，不主动触发卖出。

### 10.2 账户级防护

账户级有两条外生硬约束——券商授信额度与强平线——和一条估值型内生约束——§9.3.1 股债总仓位上限，口径见个人投资体系 §4。授信额度 = 当日净资产 `N` × 66.6%，不设金额上限；融资负债读 §2 的账户快照台账。每日实际可用资金为：

```text
现金 + N × 66.6% − 当前融资负债
```

该值作为 §8.2 的 `--funds`。用户回报券商可用保证金时，`--funds` = 券商可用保证金 + 现金（现金另计，用户未报现金即记 0），不按上式估算；上式只在未回报时使用。负债超过授信额度时不可新增买入，卖出款先偿还超额负债：可用资金为负时 `--funds` 照给负值、不取 0，扫描器以当日卖出款先补足该缺口，余额才进 §9.3.2 第 5 步买入。触及账户级阈值时在当日报告显式提示；未触及时不重复展开。股债总仓位上限受限期间授信视为 0：可用资金 = 现金 − 融资负债（扫描器 `--cash`／`--debt`，未给时读账户快照台账），为负时卖出款先偿债；当日报告列出利差、观测日、触发线、恢复线与上限状态。

### 10.3 策略收益跟踪

策略基准日 2026-08-28，基准净资产 = 该日账户快照 `net_assets_cny`（`strategy_base_net_assets_cny` 列）。账户快照每日登记 `net_assets_cny`、`external_cash_flow_cny`（有流入／流出时另填 `net_assets_before_flow_cny`）后运行 `python3 scripts/strategy_return_tracker.py --write` 重算下表策略列；`--check` 只核对不写。

| 列 | 取值 |
| --- | --- |
| `external_cash_flow_cny` | 当日外部现金流：用户外部资金／资产转入为正、转出为负，无则 0；分红、佣金税费、融资借入与偿还属组合内部记账，不计 |
| `net_assets_before_flow_cny` | 有外部现金流当日、流入／流出发生前的净资产估值；没有估值留空 |
| `strategy_nav_basis` | `exact`：当日无外部现金流，或已填 `net_assets_before_flow_cny`；`eod_approx`：有外部现金流但无流前估值，按现金流发生在当日收盘前最后时点计 |
| `strategy_unit_nav` | 策略单位净值，基准日 1；日收益 r = (N − F) ÷ N₋₁ − 1（`eod_approx`），或 r = N_pre ÷ N₋₁ × N ÷ (N_pre + F) − 1（`exact` 且 F ≠ 0）；单位净值 = 前一快照日单位净值 × (1 + r)，保留六位小数 |
| `strategy_return_pct` | (`strategy_unit_nav` − 1) × 100，保留两位 |
| `account_peak_net_assets_cny` | 基准日起 `strategy_unit_nav` 最高值 × 基准净资产 |
| `drawdown_from_peak_pct` | (`strategy_unit_nav` ÷ 基准日起最高单位净值 − 1) × 100，保留两位 |
| `strategy_epoch` | 策略纪元标签；影响估值、选股或下单的实质规则变动自生效日起换新标签：纪元表落在 `strategy_return_tracker.EPOCHS`（标签、生效日），`--write` 按行日期自动标段，`--epoch <标签> --from <日期>` 只作一次性覆盖；单位净值、峰值与回撤连续不重置；文档、展示与指标算法修订不换纪元。`E2` 对应 2026-09-10；`E3` 自 2026-09-11 起（2026-09-10 收盘后采纳）；`E4` 自 2026-09-15 起，使用 §9.3.3 确认成交冷却（2026-09-14 收盘后确认，T+1首个执行日） |

基准日前各行的策略列只存历史数据，不参与计算。快照日期不连续时按相邻两行链乘。当日报告账户段列出策略收益率、策略期回撤与纪元。

### 10.4 影子组合

影子组合主比较从 §10.3 用户指定的策略基准日开始，规则换纪元时连续递推，不重置持仓或净值。主比较落点 `data/processed/shadow_portfolio/since_20260828/`；`e4/` 只保留为09-14收盘起的分段对照，不能代替主比较。读取各目录的输入与规则指纹，不得用今日估值、名单或实盘持仓覆盖旧输入与影子状态。

1. 以基准日收盘实际现金、负债、股数、成本及止损锚初始化；按 §9.3 独立递推，持仓分歧后不重新贴合实盘。买入冻结与 L3 闸门读取原信号日生产输入。
2. 缺少执行时段逐笔行情时，以次一交易日收盘模拟成交并标明近似；费税与融资参数读取冻结的 `BASE`。报价、账户、成交或公司行动无法闭合时停止更新，不以零值补缺。
3. 当日生产扫描与实际成交回写完成后，执行 `python3 scripts/shadow_from_origin.py capture --as-of YYYY-MM-DD`，再通过 `scripts/slurm/shadow_origin.sbatch` 运行完整路径。输出逐日净值、模拟成交、当前持仓、资金核验和阅读报告；模拟成交不得写入实盘持仓或实盘冷却凭据。旧E4独立段冻结于原建立版本，只作历史辅助。
4. 建立日前的区间标为历史回放，建立后的完整交易日才标为前向观察。实质规则变化记录生效日及当时配置，跨纪元保持影子账户连续；固定现行规则回放另列为反事实，不冒充当时执行。代码指纹变化须先复核并显式建立新记录。未取得初始批次历史的股息税、实盘未分类费用与券商实时额度差异分别列示，不计作策略超额收益。
5. 期初对账先查后续持仓订正与决策日志。已确认的少记股数须纳入重建；成交日期仍有两种可能时分别计算期初情景，不伪造现金、价格或成交。后续确认日期后，追加带来源与指纹的订正，主比较及后续更新只采用确认的期初情景；排除的情景保留为历史证据，原日快照不覆盖。券商报告净资产与持仓收盘重估净资产分别保留，收益明确各自分母；未闭合的对照标为有条件结果。

## 11. 持仓记录与跟踪

### 11.1 持仓侧边界

持仓侧只记录仓位、公告、估值和成交。买卖结论只由 §9.3 产生。

### 11.2 持仓表

`data/processed/a_share_holdings.csv` 固定五列：

```text
security_code, security_name, current_shares, cost_basis, entry_stop_price
```

`cost_basis` 是**持仓均价**（买入按股数加权、减持不变、除权按 §11.4 折算），是 §9.3.1 涨幅减持行与换仓优先级的判据；`entry_stop_price` 是 §9.3.5 唯一整仓止损字段。

### 11.3 每日跟踪

```bash
python3 scripts/track_holdings_daily.py --as-of YYYY-MM-DD
```

逐票检查当日公告、披露、重大事项、产业和竞品信息，并显示合理价、空间、`P/V`、MA20、MA60、生效止损线与是否命中、涨幅减持是否命中。行情缺失必须标为“数据缺失”，不得显示为“持有”。收盘、MA20 与生效止损线的 MA60 走 §8.3 的同一份取数实现，涨幅减持命中判定与扫描器同一实现（`holding_trim_signal`）；`P/V` 读持仓侧带，与候选侧不同时并列显示；生产带的证据截止与扫描器同由信号日自动推导。银行与保险的扫描、跟踪、阅读版及成交估值统一调用 `screen_daily_volume_price_signals.resolve_live_band`，国债利率取 `observed_on ≤ 信号日` 的最新行，股利锚与除权处理调用 `bank_dividend_intrinsic`；区间显示按 §6.5.1 的带宽。缺失利率或完整财年分红时，合理价与 `P/V` 留空并注明数据缺失。

### 11.4 除权除息

除权日按交易所除权参考价同一公式调整：

| 分派 | 带、止损价与 `cost_basis` | 股数 |
| --- | --- | --- |
| 每股现金红利 `D` | 原值 `− D` | 不变 |
| 每 10 股送转 `k` 股 | 原值 `÷ (1+k/10)` | `× (1+k/10)` |
| 每 10 股配 `r` 股、配股价 `p` | `(原值 + r/10 × p) ÷ (1+r/10)` | 认购则 `× (1+r/10)`、付 `股数 × r/10 × p`；不认购不变 |
| 并存 | `(原值 − D + r/10 × p) ÷ (1 + k/10 + r/10)` | `× (1 + k/10 + r/10)` |

**带的调整由建带链机械维护**：生产带文件在 §6.7 第 4 步末段按 §6.5.1 的现金与送转起算日归一化到现价口径（现金＋送转＋配股；银行与保险走股利折现、分子按财年归属，不参与减项），回测逐日状态同一规则；调整持续到公告日晚于除息日的下一份报告接管为止，重建不抹掉。事件库 `data/raw/corporate_actions/a_share_corporate_actions.csv` 的分红送转取东财、配股取新浪配股表（`rights_ratio`／`rights_price` 列），随 §6.7 第 1 步刷新。**持仓表按事件落地**：`entry_stop_price` 是历史价格，须按上表调整并永久保留；`cost_basis` 与股数同批调整。差异化分派按交易所价格口径处理。

```bash
python3 scripts/apply_holdings_corporate_action.py --as-of YYYY-MM-DD --code <代码>            # 事件取事件库当日行，缺则东财当日接口
python3 scripts/apply_holdings_corporate_action.py --as-of YYYY-MM-DD --code <代码> --cash <每股现金> --ratio <每股送转>   # 差异化分派：显式给价格口径
```

执行即写回持仓表并登记 `data/processed/holdings_corporate_actions_applied.csv`（同一代码＋除权日只登记一次，二次执行被拒绝）；配股缺省认购，`--no-subscribe` 不认购。跟踪器的检出按台账区分「已处理／未处理」（现金送转读东财当日接口，配股读事件库当日行），并对近 30 日事件库有除权而台账无登记的持仓提示疑似漏调；当日报告必须显示“当日持仓除权除息：无/名单”。

### 11.5 成交回写

用户确认成交后：

1. 更新持仓股数与成本；清仓删除该行。
2. 由零股建仓时按 §9.3.5 写入止损价；加仓不改。
3. 运行 `python3 scripts/resolve_trade_valuation.py --as-of YYYY-MM-DD --code <代码> --price <成交价>`，取输出的合理价、候选侧与持仓侧 `P/V`、估值来源；决策日志追加 `execution_record`，记录方向、股数、成交价、当日 `P/V` 和对应规则。
4. 对 §9.3.3 适用的实际净成交运行下列命令登记冷却凭据；`--tranche` 使用原信号日档位，`--rule` 为 `buy`／`gain`／`exit`／`swap`。未成交、完全对冲不登记。当天已扫描则登记后重跑当天扫描。

```bash
python3 scripts/record_cooldown_execution.py \
  --execution-id <本地成交记录标识> --signal-date <原信号日> --as-of <成交日> \
  --code <代码> --name <名称> --side <buy或sell> --rule <规则> \
  --shares <实际净成交股数> --price <实际成交均价> --tranche <原信号日一档金额>
```

5. 次日自动纳入跟踪。

## 12. 改参数与回测验证

参数依据与全部历史读数只查 `docs/Ashare_backtest_log.md`。工作流正文只保存 §9.3.1 当前选择。

### 12.1 验证纪律

新候选先登记轨道，登记在跑数之前完成，跑完不得更换：

* **轨道 A（机制修复）**——与本文件成文标准、实盘可执行性或 `docs/000_personal-investment-system-v1.zh.md` 原则不符者。轨道 A 的依据须指向本文件的具体条款或可复现的实盘差异，指不出的改走轨道 B。采纳依据为机制正确性，回测只作护栏：第 2 款的闸门与否决不得触发，主读数与复利读数（全样本表）各自损失不超过 1pp。
* **轨道 B（收益动机）**——其余全部，按第 2、3 款的决策读数判。

两条轨道都按以下顺序验证：

1. 先确认数据、股票池有效期、复权、手续费、整手、融资和执行延迟均与 `BASE` 一致。
2. 预先按预计实盘持有期选收益主窗口，缺省取 5 年。滚动窗口**月末锚定**：窗口末日 = 每个自然月最后一个交易日，首日 = 60 个月前同月末，年化按实际日历年数，回撤与 Sharpe 用窗口内逐日净值。

   **计量口径（summary 与扫描输出行均带 `计量版本`，现行 m3）**：全期 CAGR = (期末净资产 ÷ 初始资本)^(365.25 ÷ 首个与末次净值日的日历天数) − 1；全期 Calmar = 全期 CAGR ÷ 全期最大回撤；Sharpe（全期与滚动窗口同一函数）= 逐日超额简单收益均值 ÷ 样本标准差 × √244，超额收益 = 净值日收益 − 无风险日收益，无风险日收益 = `data/reference/cost_of_equity_inputs.csv` 中 `observed_on` ≤ 前一净值日的最新年率 × 相邻净值日日历天数 ÷ 365.25，无可得利率的区间按 0 计并报 `rf覆盖率`。`--report` 按文件首行 `#METRIC` 解析，不同计量版本的读数不配对；计量版本变更时 `BASE` 与在评候选的全样本／A／U 同批重算，旧读数留台账、新旧差异与判定翻转表写回测日志，再重登在册读数。m3：水平读数与交易路径同 m2，只把主读数改为同窗口配对；summary 增 `滚动5年窗口年化`（`YYYY-MM=年化;…`，月末锚定窗口按末月配对），扫描文件在每条数字行后落 `#WIN5|标签|起点|序列` 行；m2 读数只读，不与 m3 配对。

   标准起点集 = 路径长度 ≥ 10 年的全部半年档起点，执行列表读取 `sweep_backtest_configs.DEFAULT_STARTS`；数据末端推进使新档满 10 年时补入并重登读数。标准起点集上**决策读数只有五项**：主读数 = 同起点同窗口的滚动 5 年 CAGR 先相减、起点内取中位，再取跨起点配对差中位；复利读数 = **全期 CAGR** 的配对差中位；坏情形 = 滚动 5 年 CAGR P25（**起点内**月末窗口的分位；P10 不作决策）的配对差中位；闸门 = 滚动 5 年回撤中位不得变深超过 3pp；否决 = 滚动 5 年负收益窗口占比由 0 转正（过半起点；对照已有负窗的起点不计）。判定前先校验两表两臂的起点集合等于标准起点集、每个起点的同窗窗口集合相同、决策字段均为有限值，任一不满足即「不可判」并列出缺陷；取交集的共同覆盖读数只作诊断、须单独标记，不进判定。坏情形、闸门、否决取全样本表；**主读数与复利读数在全样本表与去赢家表（剔除集 A）各取一份，四个读数按下式判**：均 ≥ −0.15pp → 可采纳；**回撤通道**：主读数两表均 ≥ −1pp、复利读数两表均 ≥ −0.15pp、全期最大回撤配对差中位两表均 ≤ −5pp（更浅）、滚 5 最差窗口配对差中位（全样本）≥ −0.15pp，且两表各起点 `BASE` 最大回撤区间按日期重叠归并后、候选更浅 ≥ 5pp 的区间不少于两段 → 可采纳·回撤通道；一表的某项落在 [−1pp, −0.15pp) 且另一表同项 ≥ +1pp → 报用户裁定；其余不采纳。闸门与否决对两种可采纳一律适用。正号起点数只报不判。**臂间比较与「未来年化表现」的表述基准一律为复利读数**，对照表按 Δ年化 排序。未来年化的水平引用只用全期口径读数——年化（全期 CAGR）、互不重叠 5 年块中位、长跑年化；滚动重叠窗口的水平值只描述窗口分布，不作未来预期引用。Δ 读数与符号数描述已过历史，不作未来 Δ 的点预测引用。

   **标准指标集**（每轮扫描必报，全样本与去赢家两个口径各出一份、同表并列，一个口径的读数不得替代另一个）：滚 5 中位／P25／最差／回撤中位／Calmar 中位／Sharpe 中位／负收益窗口占比；全期 CAGR 中位／最大回撤中位／Calmar 中位／Sharpe 中位；互不重叠 5 年块中位（自最新窗口末月往回每 60 个月一窗、首尾相接零重叠，取中位）；长跑锚点 2009-11-01 与 2011-11-01 各自的全期 CAGR 与最大回撤，两个锚点都报；滚 3 中位与回撤中位；逐年收益中位与最差；年均换手（参考项，不进第 4 款判定）；平均仓位（＝持仓市值 ÷ 净资产，融资下可超 100%）。每项报三个数：水平值、逐起点配对差中位、正号起点数——长跑锚点是单起点，只报水平与配对差，不报符号数、不进任何判定。滚 5 中位的逐起点配对差是 m2 主读数，自 m3 起只描述。另出集中度表（持仓数、单票权重中位／P90／最大、前三权重中位、单票超 60% 天数占比）与滚动 10 年 CAGR，只描述不排序。集内除五项决策读数外一律只描述不排序；两臂比较一律取逐起点配对差，不比较两个水平值。不得看完结果再换主窗口或换读数。两层分位不要混：符号数是标准起点集层，P25／最差是起点内窗口层。

   **跨起点尾部**（每轮必报，只描述不判，直接取标准起点集的最值）：实际最差滚 5 CAGR 及其起点与窗口末日；最深全期最大回撤及其起点与区间；最低担保比例及其起点与日期；最低股票同跌缓冲及其起点与日期；最低现金及其起点与日期、负现金日数合计；强平模拟路径次数合计与受影响起点数；出现 5 年亏损窗口的起点数；`rf覆盖率` 最小值；数据末端 = 各起点末次净值日的最大值。

   **强平缓冲**：引擎在每日担保比例检查的同一时点取 S = 持仓市值、C = 现金、D = 融资负债、k = 维持担保比例、R = (S + C) ÷ D，总资产冲击缓冲 = 1 − k ÷ R，股票同跌缓冲 = (S + C − kD) ÷ S；D = 0 或 S = 0 记不适用，负值原样保留；summary 取全路径最小值及其日期，不用日末现金配 summary 最低担保比例重算。

   **资金记账**：日末盯市对当日新建仓取成交日收盘，成交日无报价沿最后可得价格；买入委托金额加买入费税须落在现金 + 剩余授信之内，整手取整、按手建仓、割肉买回与同日对冲后的净额按最终委托复核，不足则按手缩量、缩到 0 即跳过；同日对冲退回卖出款前先在授信内融回，融不回的部分不对冲；配股认购款不足部分仍按融资计。summary 报 `最低现金`／`最低现金日`／`负现金日数`（日末现金），现行 `BASE` 的负现金日数须为 0。

   **报表版面**：扫描报告首页只有【决策读数】（全样本与剔除集 A 各一份）、【采纳判定】、【跨起点尾部】三段；标准指标集、配对差、集中度、长跑锚点、滚 10 为附表，字段、台账与第 4 款资格计算不变。
3. 报逐起点配对差中位和正号起点数，不比较两个独立中位数的差。每轮扫描同时出去赢家对照表，剔除集取两个：**A** = `BASE` 臂 2011-11-01 起点按代码汇总逐日「盈亏 ÷ 前一日净资产」累计贡献的前五名（盈亏 = 持仓市值变动 − 当日买入 + 当日卖出与分红，费用、股息税、融资利息不摊；取 summary `前五赢家` 列，逐周期贡献在 trades 的 `contrib` 列）；**U** = A 与候选臂同起点前五名的并集。两个剔除集都用 `--exclude-codes` 从全部臂统一剔除、不改面板，Δ 各自对同剔除集的 `BASE` 配对；候选臂之间只比同一剔除集下的读数。`sweep_backtest_configs.py` 缺省自动跑 A，`--no-ex-top5` 只用于纯补跑；U 走 `scripts/experimental/ex_winner_symmetry.py`；剔除集须按锚点固定时（第 7 款滑点各档）给 `--exclude-codes <代码>` 跑固定剔除集单遍。
4. 候选臂在剔除集 U 下、标准指标集各项配对差中位均 ≥ −0.15pp，或至多一项落在 [−1pp, −0.15pp) 而其余各项均 ≥ −0.15pp（长跑锚点、年均换手与集中度表不计入；滚 5 与全期的 Calmar、Sharpe 四项按比率单位判，−0.15pp 对应 −0.005、−1pp 对应 −0.033），记为**去赢家全面优秀**，登记为待考察候选并写入 `docs/000_Ashare_workflow_open_issues.md`。该判定不构成采纳，也不放宽第 2 款的门槛。采纳前须另行补齐三项：① 换仓边际在该臂上按 0.01 一档重新剂量扫描，不得沿用 `BASE` 的边际；② 剔除赢家只数取 1／3／5／10 的剂量曲线，四档读数须同向；③ 第 10~12 款读数齐备。三项齐备后按第 8 款处理。
5. 参数至少扫描相邻区间，优先选择宽平台，不选择单点峰值；±0.15 个百分点以内视为噪声。
6. 增加互不重叠的持有期或逐年检验；共享终点的多个起点与重叠滚动窗口不视为独立样本。
7. 检查可执行性、幸存者偏差、未来信息和多重比较；绝对收益不当作未来预期。

   **执行成本压力**（仅用户明确要求时运行）：默认回测使用 `--slippage-bp 0`，手续费、税费与融资成本照常计入；参数初筛、机制修复及采纳前验证均不主动安排滑点测试，未运行不构成材料缺失或采纳阻碍。保留滑点代码、配置与报表功能；复用历史实验批处理时也须按本条触发条件选择测试项，不自动附带滑点测试。

   用户明确要求后，候选与 `BASE` 各按每边滑点 0／10／20／30bp（`--slippage-bp`：买入成交价 × (1 + bp/1e4)、卖出 × (1 − bp/1e4)，进股数、整手、可用现金、成本、费税；盯市价与信号价不变；同日买卖先净额对冲、只对净额收；强平与退市清仓同样收；分红、送转、配股认购不收）跑标准起点集两遍，同档配对，剔除集 A／U 按 0bp 锚点固定（`--exclude-codes` 单遍）；报各档主读数与复利读数的 Δ、滚 5 回撤／最低担保比例／强平次数的变化，以及第 2 款判定是否随档位翻转；`BASE` 各档对 0bp 的配对差同表列出；档位不作否决线。入口 `scripts/slurm/oi148_slippage.sbatch`，报表 `scripts/experimental/oi148_slippage_report.py`。
8. 只有第 1~7 款的适用要求通过、第 10~12 款读数齐备且用户裁定后，才修改 §9.3.1、生产常量和回测 `BASE`。
9. 实验过程写入回测 log：每节不超过 1.5 KB，只写「测了什么／结论／决策读数／落地」，完整表格与逐臂读数放 `data/experiments/<实验目录>/` 并在节内给目录名；最终版本变化写入 changelog，每行只写规则变化与落点、依据只给回测日志节号；当前操作只写回本文件。
10. 信号层三表：`scripts/experimental/selection_edge_audit.py`（边际选择检验、排序信息量、换仓方向性；回测须带 `--candidate-log` 与 `--trade-log`）与 `scripts/experimental/panel_tier_forward.py`（`P/V` 分档前向回报）。采纳候选在候选臂与 `BASE` 上各跑一遍并报差；另每季在 `BASE` 上重算一遍作不变量检验。配对比较报逐日配对差中位、为正日数与逐年同号年数；股票×日期分组分布须标明重复观测，不能把行数作为独立样本量。换仓方向性一表须同报 `scripts/experimental/swap_regime_control.py` 的四表对照（面板层 `P/V` 信息量、合成换仓、`P/V` 匹配对照、样本独立性），匹配对照的容差至少取 ±0.04／±0.10／±0.15 三档、只报符号稳健的读数；该表的样本量按不同 `(源, 标的)` 配对数计，不按日数；只有与合成换仓反号的年份计入机制层结论。三表不进第 2 款的决策读数，读数写入回测 log。

    **单票前向收益引用**：明确买入线、估值版本、历史股票池、是否包含趋势条件、排名范围、信号日/测量起点及累计/年化口径。同报逐日、首次符合指定信号至收盘跌破当日复权 MA60 的周期去重、周期去重后同股前向窗口不重叠三组；不因排名/PV档位变化或 MA20 波动重新计数。若按实际止损线重置，另列 §9.3.5 锚止损口径，不与 MA60 周期混称。计数周期结束不截短固定期前向回报；失败信号保留，终点不足单列。报信号数、完整窗口数、公司数、逐公司/逐年分布；同股不重叠仍不证明跨股独立。复现与检验入口 `scripts/experimental/pv_episode_forward.py`、冻结旧排名表的 `rank_episode_forward.py`，配置/证据随实验登记。

11. 采纳候选报 `scripts/experimental/delta_attribution.py` 的前三只贡献占比（按 trades `contrib` 列，与第 3 款同一把尺）；超过 100% 者不作采纳依据。
12. 引用正读数时同报本族已试臂数，按 `data/backtest/scan_arms_index.csv` 的臂名计（`clean_derived_artifacts.py` 归并后自动重建）；当前逐路径读数取 `data/backtest/scan_summaries.csv`。

历史面板 `effective_from` 与 `effective_to` 均为有效期边界，结束日包含在内。禁止把区间起点当成完整快照，也禁止手工修改面板 CSV；名单变化先改判定源，再运行装配脚本。换码主体的双代码区间约束见 §8.3。

换估值口径或换宇宙做 A/B 时，使用 `scripts/experimental/align_buy_line.py` 把买入线重解到同一在册合格面，保留四位小数。**对齐容差**：先在新口径逐日状态上计算原买入线的下侧合格面，它与在册合格面之差的绝对值 < 0.2pp 时保留原线（脚本 `--tolerance-pp 0.2` 缺省判定并打印两侧合格面），在册合格面不随之改写、仍取上次实际重解时的值，避免多次容差内漂移累积；达到或超过容差才取对齐解并重登在册合格面。换仓边际按 0.01 一档重新扫描，不随买入线缩放。

**买入线独立剂量扫描**：固定估值口径与股票池，把买入线作为待测参数，不作合格面对齐或容差回退；逐档报告实际合格比例，其他交易参数固定，以当前 `BASE` 做同起点全/A/U对照。范围、步长与诊断档先登记；按本节判断相邻平台和风险，不以扫描最高单点自动修改生产。

**横截面比例买入研究**：`--buy-top-pct q`（0关闭，q∈(0,1]）替代固定P/V准入上限。分母为信号日有效面板中候选侧价格、价值、P/V均有限且为正的公司；按P/V升序、同值按代码升序，取前⌊q×N⌋只，再走原走势、持仓及执行约束，不补齐被后续条件挡下的名额。T+1只执行T日选中且成交日仍在册的公司；掉出排名不新增卖出规则。A/U剔除后在剩余信号日宇宙重算排名与分母；换仓仍用原P/V与原边际。必须报告逐日人数、实际比例、隐含P/V门槛分布和逐年读数，按本节预登记、同起点对照和平台标准筛查；生产缺省关闭。

**股债性价比仓位约束**：生产规则见 §9.3.1 股债总仓位上限行，`BASE` 显式带 `--equity-bond-mode cap --equity-bond-metric spread --equity-bond-restore-above` 与三个数值参数 `--equity-bond-threshold`（触发线）、`--equity-bond-lower`（上限）、`--equity-bond-release-threshold`（恢复线），取值只在 §9.3.1 股债总仓位上限行；恢复门槛只支持 `cap/spread/restore-above`，须有限且不低于触发门槛。未给恢复门槛时保留同阈值切换的历史研究语义；其他模式与参数为研究开关。输入 `--equity-bond-data` 的股债利差 = 宽基指数整体滚动盈利收益率（1/PE_TTM）− 中国10年国债到期收益率，利率用小数；不用成本输入表里的常数ERP。数据注明指数、来源、观测日与债息观测日，PE须有限且正，债息须有限；禁止未来回填。信号取T日收盘已知观测，T+1执行；分位为当前利差在信号观测日前最多60个有效月观测中的中秩，至少12条，当前观测不参与历史分布。上市前/历史不足时保留原策略并记覆盖；序列开始后的估值观测过期（门槛见 §9.3.1）或债息在估值日已过期超过10天时报错，禁止静默放行。

研究动作分开标记：`credit`低于阈值时授信归零、现金与后续卖出款先偿债，不主动卖券；`cap`按绝对利差或历史分位阈值切换总仓位上限；`ramp`将历史分位在两端点间线性映射到上下仓位上限。总仓位分母为当日净资产，配置范围0～160%；上限只限制买入，不强制补仓。主动约束在常规卖出后按可交易持仓比例减仓、向上取整到一手并先偿债；停牌延后、记录未满足上限，不用陈旧价格成交。买入在整手/兜底及同日对冲前后校验总仓位与费用后的资金余量，禁止绕限；仅在显式启用股债约束时生效，生产BASE已启用。融资利息、交易费税、滑点、强平与股票选择继承BASE。实验须预登记相邻阈值、固定仓位对照、覆盖及触发频率，按本节做全/A/U同起点配对；生产采纳仍走第8款。阈值以上完整恢复的分支即引擎 `--equity-bond-restore-above`（研究批次的 `high_base_engine.py` 与之等价）。

**融资约束替代规则研究**：独立研究入口 `data/experiments/exp_equity_bond_opt_20260910/engine.py --eb-policy <臂名>`，规则与扫描网格先冻结于该目录 `preregister.md`／`grid.json`。可测试利差触发后的总仓位上限、恢复融资的较高利差门槛或连续月数／趋势确认、指数整体 PE 及其历史分位、指数价格相对 60 个月均线的偏离。均使用信号日前已知月观测；均线取已完成月份收盘价，缺少所需历史时回退当前 BASE 并记录覆盖；状态从全部可得历史逐月重建，不随回测起点重置。恢复条件仅恢复融资与原买入规则，不强制补仓。逐臂记录触发和恢复日期、受限日数、实际仓位及完整全/A/U结果；严格核验全部标准起点与配对窗口一致，负窗否决按本节“由 0 转正”计数。研究不改变生产参数，采纳仍走第 8 款。

当前参数读取 §9.3.1；在册合格面、基准读数和实验证据从 `docs/Ashare_backtest_log.md` 查找。配对只使用同纪元、同计量口径、同起点和同剔除集的基准。报告参数选择依据及取舍，不将历史最优读数作为未来收益承诺。

## 13. 改规则前自检

1. 是否先改本文件的唯一标准，再改代码？
2. 是否存在真实执行点，而不是只有文字？
3. 新列、状态和告警是否有非空覆盖校验？
4. 是否混用了公告日与报告期末、累计与单季、复权与未复权、盘中与收盘？
5. 是否在其他章节或文档重复保存了同一阈值？
6. 是否同步生产常量、回测 `BASE` 和参数同步测试？
7. 是否使用多起点、配对差、平台和非重叠时期验证？
8. 是否明确处理了失败退出与未验证项？
9. 是否更新第 1 行版本号、changelog 和决策日志？
10. 是否只提交本次相关文件并通过目标测试？

## 14. 执行方式

日常请求可直接写：

```text
请按 docs/000_Ashare_workflow.md 执行 YYYY-MM-DD 的 A 股每日扫描，
更新固定输出与决策日志，并给出 T+1 尾盘执行清单。
```

执行时不要求用户重复解释规则。若当前数据或已知缺陷使某一步不可信，明确报告降级口径并停止产生受影响的执行结论。

## 15. 版本与历史

当前版本只认第 1 行。版本变化记入 `docs/Ashare_workflow_changelog.md`，回测依据记入 `docs/Ashare_backtest_log.md`；两者只保留当前纪元，旧纪元在 `docs/archive/`；完整旧正文可从 Git 历史恢复，不复制回本文件。
