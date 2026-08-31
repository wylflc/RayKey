# A股选股-估值-量价操作流程 v4.107

> 本文件只保留当前生效的操作指引。第 1 行是唯一版本真值，供 `scripts/workflow_decision_log.py` 写入决策日志。
>
> 历史版本变化见 `docs/Ashare_workflow_changelog.md`；回测过程、参数比较与被否决方案见 `docs/Ashare_backtest_log.md`；已知未修缺陷见 `docs/Ashare_workflow_open_issues.md`。正文不保存历史参数、实验读数或退役机制。

## 0. 任务路由

| 请求 | 执行章节 | 主要入口 |
| --- | --- | --- |
| 今日 A 股每日扫描 | §9.1、§9.3、§11 | `screen_daily_volume_price_signals.py`、`track_holdings_daily.py` |
| 今日该买、加、减、换什么 | §9.3 | §9.3.1 参数表与 §9.3.2 顺序 |
| 今日持仓跟踪 | §11 | `track_holdings_daily.py --as-of` |
| 季度全市场质量审查 | §5.1-§5.4 | `build_quarterly_quality_review_queue.py` |
| 对 `worth_attention` 做 L1-L3 分层 | §5.7-§5.8 | `a-share-quality-tiering` 工作流 |
| 更新估值与核心池 | §6 | §6.7 估值重建链 |
| 财报披露后的滚动更新 | §7 | `build_report_update_queue.py` |
| 单票研究（含点名建档与 L4） | §5 → §6 → §9.3 | 逐层判断，任一层否决即止 |
| 修改估值、交易规则或回测参数 | §12-§13 | `sweep_backtest_configs.py` |

所有可复核结论均按 §2 写入决策日志。买卖机制只认 §9.3；账户级风险只认个人投资体系 §4 的两条外生硬约束（券商授信额度、130% 强平线）。

## 1. 目标与边界

本流程把 A 股研究固定为五个阶段：

1. 全市场三类初筛与质量分层。
2. 对 `worth_attention` 公司建立合理价区间。
3. 财报与重大事件后的滚动复核。
4. 每日行情、估值与相关性扫描。
5. 持仓公告、估值与成交记录跟踪。

执行原则：

1. 业务质量决定是否值得持续研究；价格和题材不进入质量判断。
2. 合理价区间只由基本面证据与模型改变；价格只改变当日档位和 `P/V`。
3. `P/V` 与走势条件按 §9.3 机械产生执行清单，不临时加入主观快速通道。
4. 流程终点是执行清单；实际下单由用户决定。
5. 原始数据、过程数据、当前结论和历史记录分开保存。
6. 同一口径在本文件只定义一次；其他章节和文档直接引用定义位置。

## 2. 唯一真值与固定产物

| 内容 | 唯一真值 |
| --- | --- |
| A 股证券名单 | `data/raw/a_share_securities.csv`；历史快照在 `data/raw/snapshots/`，不可修改 |
| 三类初筛 | `data/processed/a_share_attention_triage.csv` |
| L1-L3 分层与参考分 | `data/processed/a_share_watchlist_quality_tiers.csv` |
| 逐票研究档案 | `data/processed/a_share_valuation_dossiers.csv` 与 `data/companies/<代码>_<名称>/` |
| 当前生产模型带 | `data/processed/a_share_pool_model_bands_adopted.csv`（候选侧） |
| 持仓侧模型带 | `data/processed/a_share_pool_model_bands_hold.csv`（逐票取候选侧与 B2 较高 V；§9.3.1 减持线与换仓来源读它） |
| 核心估值池 | `data/processed/a_share_core_valuation_pool.csv` |
| 核心池阅读版 | `data/processed/000_a_share_core_valuation_pool.md` |
| 持仓 | `data/processed/a_share_holdings.csv` |
| 持仓除权处理台账 | `data/processed/holdings_corporate_actions_applied.csv`（§11.4，只追加） |
| 账户快照 | `data/processed/portfolio_account_snapshot.csv`；可用资金按 §10.2（券商可用保证金优先），策略收益率、峰值与回撤按 §10.3；`credit_line_cny` 列已退役，仅存历史数据 |
| 每日买入计划 | `data/processed/daily_entry_plan.csv` |
| 每日卖出清单 | `data/processed/daily_sell_plan.csv`（止损复核、减持、涨幅减持、出名单、换仓、余仓清空） |
| 比例冷却计数器 | `data/processed/daily_cooldown_state.csv`（§9.3.3，扫描器每日读写） |
| 每日持仓跟踪 | `data/processed/daily_holdings_tracking.csv` |
| 每日阅读日志 | `data/processed/000_daily_scan_log.md` |
| 审计日志 | `data/processed/a_share_workflow_decision_log.csv`，只追加不覆盖 |
| 财报更新队列 | `data/interim/a_share_report_update_queue.csv` |

每条质量、估值、名单迁移、规则采纳或成交结论必须写入决策日志，至少包含：时间、阶段、对象、结论、简要理由、输入文件、输出文件、执行者、工作流版本和稳定 `decision_id`。纠错或替代旧结论时填写 `supersedes_decision_id`。

## 3. 核心术语

| 术语 | 定义 |
| --- | --- |
| `worth_attention` | 通过 §5 三类初筛、进入持续研究的公司集合；它不是买入清单 |
| `boundary_pending` | 证据不足或当前缺乏持久优势、但保留硬触发复核可能的公司 |
| `documented_not_attention` | 用户点名建档、经分析判无护城河的公司：有档案、L4 分层、参考分与估值区间，但不在 `worth_attention`，任何档位不可买（§10.1 第 1 条） |
| `garbage` | 仅因坐实治理灾难或结构性绝望行业而永久排除的公司 |
| L1/L2/L3/L4 | §5.7 的业务质量分层；不直接决定买入资格（不可买由名单归属决定） |
| 合理价 `V` | §6 当前生产带上下沿的中值 |
| `P/V` | 未复权现价 ÷ `V`，交易规则使用的估值比率（唯一实现 `scripts/pv_ratio.py`，扫描器／跟踪器／阅读版／档案同源）；薄权益带（净负债 ≥ 50% 企业价值）按 §6.5.1 守卫判无法估值、无 `P/V` |
| 空间 | `V ÷ 现价 − 1`，仅作阅读展示 |
| 合格集 | 通过 §9.3.1 买入线、走势条件、冻结、L3 战术闸门与相关性过滤后的股票，按 `P/V` 升序 |
| 一档 | 按 §9.3.1.1 从当日净资产计算的单次交易金额 |

## 4. 总流程

```text
A股证券名单 ∪ 财报中出现的A股证券
  → §5 三类初筛
  → 对 worth_attention 做 L1-L3 分层
  → §6 建立并校验生产模型带
  → §7 根据披露与事件滚动复核
  → §8 取得收盘、MA20、MA60、P/V、252日相关性
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

1. 先做资本复制测试；存疑不进入 `worth_attention`。
2. 股价、估值、市值、主题热度和短期盈利不影响三类判断。
3. 公司层面平庸但行业并非结构性绝望，判 `boundary_pending`，不判 `garbage`。
4. `garbage(governance_fraud)` 必须有行政处罚、司法文书、审计意见或交易所处分等权威证据；仅有嫌疑时判 `boundary_pending` 并写核验触发。
5. 同业对比必须检查差异化位置；“不如第一名”不等于被全面覆盖。
6. 行业增长放缓本身不是初筛排除项；只在壁垒载体被破坏时影响质量。

行业特殊口径：

| 场景 | 操作口径 |
| --- | --- |
| 规制基础设施、普通银行、极端牌照业务 | 只有不可复制性已持续转化为高于同业的回报，才可进 `worth_attention` |
| 银行 | 关注池只保留系统重要性代表和长期 franchise 质量最优者；普通规模型银行留 `boundary_pending` |
| 保险 | 同银行口径：只保留系统重要性代表与长期 franchise 质量最优者——判据为**十年维度** ROE 中位与稳定性高于同业（短期同业 ROE 受权益投资收益推高不作数）；普通寿险留 `boundary_pending` |
| 商品与资源 | 同时要求稀缺/配额、成本曲线和规模/储量；仅有其中一项不足以入选 |
| 资本密集周期制造 | 结构整合、技术、规模或准入壁垒已使替代客观困难时可以入选；景气本身不算壁垒 |
| 客户集中 | 区分可竞争买方与结构性单一买方；后者须有长认证、准入锁定和稳定长期 ROE，前者须证明能力可跨客户迁移 |
| 受困或 ST | 未坐实造假时按竞争力判断；控制权已更换且责任人出清时允许回到 `boundary_pending` 复核 |

具体行业校准证据只保存在 `docs/peer-group-calibration/`，执行时用来校验本节规则，不另立阈值。

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

评分细节和判例见 `docs/Ashare_quality_rubric.md`。参考分只用于同层排序：

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

对全部 `worth_attention` 公司维护估值带。用户点名的任何公司也建档并给出估值区间（含结论为 L4 者，§6.5.2）。用户点名建档但未进入 `worth_attention` 的公司，在 `data/processed/000_a_share_core_valuation_pool.md` 的 L4 归档区列示，并保留其结构化 `attention_class`；合理价只读逐票档案，不入池 CSV、不落生产带文件、无 `P/V`、不取每日行情、不进扫描与 §9.3 的任何判定。估值只生成合理价 `V`；买卖资格由 §7 的冻结状态和 §9.3 决定。

### 6.2 每日展示档位

每日以现价对照当前有效带自动重定：

| 条件 | 展示档位 |
| --- | --- |
| 现价 > 1.2 × 带顶 | 高估 |
| 带顶 < 现价 ≤ 1.2 × 带顶 | 较高估 |
| 带内 | 中性 |
| 现价 < 带底且空间 < 40% | 较低估 |
| 现价 < 带底且空间 ≥ 40% | 低估 |

展示档位不直接决定交易。原则始终是：价格改档，证据改带，任何时候不得由希望得到的档位反推合理价。

### 6.3 数据与时点

1. 建带输入不得包含当日现价、现市值、当前 PE 或当前 PB；股本可以用同一时点的总市值÷现价取得。
2. 财务数据按可得日 `available_at` 生效，禁止用报告期末代替可得日。**可得日 = `min(记录公告日, 法定披露截止日)`**（年报次年 4/30、一季报当年 4/30、半年报 8/31、三季报 10/31；唯一实现 `scripts/disclosure_dates.py`）。
3. 季报财务为累计口径；单季值用同年累计差分，TTM 用最近四个单季求和。
4. 一致预期使用逐份研报归母净利润中位数，覆盖少于三家时不得采用；禁止混用送转前后的研报 EPS。
5. 跨字段比率必须使用同一披露口径；字段缺失时整体退回上一套已披露口径，不拼接半新半旧的数据。

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
3. **外生权益按面值进每股净现金**：ROIC 路径 `net_debt_ps = (有息负债 − 超额现金 + 少数股东权益) ÷ E_op × BPS_op − x`；权益路径 `V = V(eps0 = roe0 × BPS_op) + x`；零增长锚与敏感度带同式。
4. 带文件写 `bps_operating`／`external_equity_ps`／`external_equity_cum_ps`／`shares_est`／`bps_basis_date`／`equity_anchor_mode` 列；建带结尾打印 `|x|/BPS` 分布、超过 10% 的最新带名单与各退化模式计数（§13 第 3 条）。
5. **BPS 的股本基准按数据判定**：`bps_basis_date` 由本行与上一行 BPS 之比对照送转因子按对数距离判定；回测逐日展开、生产带除权归一化、档案折算三处的**送转**窗口一律自 `bps_basis_date` 起算，**现金分红**窗口自公告日起算。

统一参数：折现率 `r = 10%`（统一要求回报率，不逐公司调整）；`g_T = 3%`；显式期 10 年线性 fade。护栏拒绝（亏损、`ROE_T/ROIC_T` 贴 `g_T`、零增长股权价值 ≤ 0、**薄权益**——每股净负债 ≥ 50% 每股企业价值）统一判「无法估值」（§6.5.2.4）。生产参数由 §6.7 的建带命令唯一给出，不在逐票档案临时改写。

所有正常模型带均为 `[0.90×V, 1.10×V]`，中值即 `V`；±10% 是展示与执行分档的带宽，不是 `V` 的统计置信区间。策略标签只作展示与同类研究，不参与生产估值计算。

#### 6.5.2 逐票估值档案

##### 6.5.2.1 P/V 与带宽

正常生产带的中值必须等于模型内在价值。生产 `P/V` 与回测 `valuation_ratio` 在未叠加预告的行上使用同一分母（`scripts/pv_ratio.py` 与逐日状态同式）；被 §6.4 叠加过的行是成文例外，生产分母比回测分母新。

叠加只写生产带 `a_share_pool_model_bands_adopted.csv`，**回测输入 `roic_bands.csv`／`roic_daily_raw.csv`／`a_share_daily_states_adopted.csv` 一律不碰**。带文件的 `forecast_overlay` 列非空即表示该行已叠加；引用回测读数论证生产行为时先看这一列。

##### 6.5.2.2 模型计算

模型计算统一由 §6.7 命令完成；档案不得覆盖模型参数或为希望得到的档位反推输入。

##### 6.5.2.3 生产带落地

`data/processed/a_share_pool_model_bands_adopted.csv` 是生产模型带唯一来源，**只含池成员**（分层表 worth_attention L1-L3；池外档案的带由 `apply_model_bands_to_dossiers.py` 直接取自全市场模型带、只落档案），**其带值恒为现价口径**：§6.7 第 4 步的叠加脚本末段按除权事件（现金自带公告日起、送转自 `bps_basis_date` 起，§6.5.1 第 5 条）归一化，`exright_note` 列非空即已折算。逐票档案只承载研究结论和当前带；`apply_model_bands_to_dossiers.py` 只覆盖带相关字段，保留 `key_metrics`、`review_triggers`、高频指标和研究备注。README 第八节「现价隐含了什么」的首段由 `build_company_dossier_readmes.py` 按生产带与池内现价机械生成（`现价 ÷ 中值 = P/V`、路径与增长/折现假设、归一化盈利倍数），`implied_growth_years` 只承载手写的可证伪命题与方法分歧，不得再写带中枢、隐含年数反解或任何带值。

**持仓侧带** `data/processed/a_share_pool_model_bands_hold.csv`：§6.7 第 4 步由候选侧生产带与 B2 池带（§6.5.1 B2 口径）逐票取 `intrinsic_value` 较高的一行，两侧各自完成预告叠加与除权归一化后再取，`hold_source` 列标明来源；成员与候选侧生产带相同。§9.3.1 减持线与换仓来源读持仓侧带；买入线、候选排序、档位、档案、阅读版与 §6 其余判定只读候选侧生产带。回测同构：候选侧读 `a_share_daily_states_adopted.csv`，持仓侧读 `a_share_daily_states_hold.csv`（§6.7 第 3 步逐 (代码, 日期) 取较高 V，`--hold-states`）。

生产 `P/V` 与回测 `valuation_ratio` 必须逐位一致（成文例外只剩 §6.4 叠加行）。**晚间披露报告的当晚吸收两侧同构**：生产在公告日戳的前一晚即用新带出信号；回测逐日状态里每条带自**可得日之前的最后一个市场交易日**起生效（`build_historical_valuation_bands.py --state-effective prev_trading_day`，缺省；前一交易日按上证指数日历取，行情库在该公告前已断的陈旧序列退回可得日生效）。带的可得日按 §6.3 第 2 条封顶（`--notice-cap statutory`，缺省）。回测的均线与建仓止损锚同样与实盘同构：均线按前复权口径折回当日股本／分红基准（§8.3），除权日止损锚与持有期峰价按 §11.4 同式折算（§9.3.5）。早于 `2025-01-01` 的陈旧模型带不进任何一层：扫描器无 `P/V`、档案层判「无法估值」（§6.5.2.4），两层同一结论。

##### 6.5.2.4 主体重置与无法估值

**主体重置**（重组、资产注入、并表或借壳使旧财务主体不可比）：在 `data/processed/entity_reset_dates.csv` 登记 `security_code,security_name,reset_report_date,growth_mode,reviewed_at,note`；`reset_report_date` 取新主体首个年报期末，`growth_mode` 取 `none`（不增长）或 `trend`（按季报趋势给增长）。§6.7 第 2 步自动读取该表：报告期 ≥ 重置日的行把比率窗口、十年守卫窗口与经营账面基年截到重置日起；重置后不足三个年报时，锚 = 最新年报比率 × TTM 因子，`none` 时 `g0 = 0`，`trend` 时 `g0 = min((TTM 因子 − 1) × 增速腿权重, g0 上限)`（TTM 因子 < 1 + `--ttm-trust-delta` 时为 0）；上年同期行早于重置日时由本行 `netprofit_yoy` 反推同期数。重置后满三个年报即回到通用路径，无需人工动作；早于重置日的行不受影响。

**无法估值**：亏损、归一化 ROE 非正、`ROE_T` 贴近 `g_T`、零增长股权价值 ≤ 0、薄权益、最新 ok 模型带早于 `2025-01-01` 时点门槛——一律判「无法估值」：档案带清空、池内可见、带显示 —、无 `P/V`、不进 §9.3 任何判定；模型重新可算后自动回归模型带。不设手工带。

#### 6.5.3 估值质量分与敏感度带（输出列，不进任何判定）

建带命令对每条 ok 带另写四列，**只用于读带时判断参数敏感度与输入可信度，不进入 §9.3 任何买卖判定，也不改带值**：

| 列 | 定义 |
| --- | --- |
| `valuation_quality_score`（0-100） | 五个分项各 20 分相加：①历史长度（可用财年 ≥8 → 20；5~7 → 12；≤4 → 5）；②回报稳定性（逐年 ROIC／ROE 的变异系数 ≤0.25 → 20；≤0.50 → 12；其余或不可算 → 5）；③终值占比（≤0.60 → 20；≤0.75 → 12；其余 → 5）；④路径与守卫（growth 未触 peak 守卫 → 20；growth 触守卫或 zero_growth → 10；equity_fallback → 5）；⑤两腿一致度（g 的资本腿与增速腿、权益口径的 g_sustainable 与 g_trailing：两腿可算且差 ≤5pp → 20；≤10pp → 12；只有一腿 → 12；差 >10pp 或皆无 → 5）。`valuation_quality_notes` 记各分项得分 |
| `v_bear` / `v_bull` | 同一引擎、五个参数同向扰动后的每股价值：Bear = g0×0.5、折现率 +1pp、终值回报 −1pp、fade 7 年、g_T −0.5pp；Bull = g0×1.25（受 g0 上限）、折现率 −1pp、终值回报 +1pp（不高于起点回报）、fade 13 年、g_T +0.5pp；zero_growth 只扰折现率 ±1pp；银行与保险（股利折现覆盖）不算。任一侧触护栏即留空。**Bull 不给交易层用**，带宽仍是 §6.5.1 的 ±10% |

建带结尾另按「每只最新 ok 带」打印路径分布（只数、市值占比、前三行业）。

### 6.6 人工复核职责

人工只处理：模型不可估原因；主体不可比（重置日与 `growth_mode`）；新证据是否触发重算；校验失败行。正常公司不逐票选择模型、倍数或带宽。

档案必须保留证据事件、证据可得日、关键指标、高频指标、下一复核点和可证伪触发。带变动后重渲染逐票 README。

### 6.7 估值重建链

以下顺序是当前唯一生产路径。重建全历史模型带属于重作业，必须独占运行。

所有生产命令只接收 `--signal-date`。证据日由 `scripts/a_share_signal_dates.py` 唯一推导为信号日之后的首个工作日（周一至周五）；调用方不得另行指定证据日。

```bash
# 1. 刷新财务输入与除权事件（逐季财务、三大报表、除权事件、rf/ERP 序列四份缺一不可）
python3 scripts/fetch_a_share_quarterly_financials.py --signal-date YYYY-MM-DD --since <当前报告期末>
python3 scripts/fetch_a_share_financial_statements.py --signal-date YYYY-MM-DD
python3 scripts/fetch_ohlcv_history.py --signal-date YYYY-MM-DD --actions-only
python3 scripts/fetch_cost_of_equity_inputs.py   # rf/ERP 序列：银行/保险股利折现（第 3 步、扫描器 --rf 缺省、档案层）与 §6.8 的 r 读它的最新行

# 2. 构建 ROIC 带与逐日状态
python3 scripts/build_historical_valuation_bands.py --all --value-model roic \
  --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
  --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --out-bands data/processed/roic_bands.csv \
  --out-daily data/processed/roic_daily_raw.csv
# 2b. B2 带与逐日状态（持仓侧第二输入；与第 2 步串行、不得并发）
python3 scripts/build_historical_valuation_bands.py --all --value-model roic \
  --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
  --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
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

# 4. 生成池模型带 → 叠加预告/快报 →（B2 池带同两步 → 持仓侧池带）→ 写入逐票档案 → 重渲染 README
python3 scripts/build_pool_model_bands.py --signal-date YYYY-MM-DD
python3 scripts/apply_forecast_band_overlay.py --signal-date YYYY-MM-DD
python3 scripts/build_pool_model_bands.py --signal-date YYYY-MM-DD \
  --bands data/processed/roic_bands_b2.csv --states data/processed/a_share_daily_states_b2.csv \
  --out data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/apply_forecast_band_overlay.py --signal-date YYYY-MM-DD --bands data/processed/a_share_pool_model_bands_b2.csv
python3 scripts/build_hold_model_bands.py   # 持仓侧池带 = 逐票取候选侧与 B2 较高 V → a_share_pool_model_bands_hold.csv
python3 scripts/apply_model_bands_to_dossiers.py --signal-date YYYY-MM-DD
python3 scripts/build_company_dossier_readmes.py   # 档案 CSV → README（§6.6 带变动后重渲染；--check 只验漂移）

# 5. 档案 → 建带卡 → 估值表
python3 scripts/build_valuation_band_cards.py \
  --tags data/interim/strategy_tag_map.csv \
  --out data/interim/valuation_band_cards.csv \
  --signal-date YYYY-MM-DD
python3 scripts/apply_valuation_band_cards.py --signal-date YYYY-MM-DD --quotes fetch

# 5.5 逐行自洽核对财务面板（检出会静默改变带的数据错误）
python3 scripts/audit_financial_panel_consistency.py --signal-date YYYY-MM-DD

# 6. 校验并物化核心池
python3 scripts/validate_valuation_bands.py \
  --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv \
  --queue-out data/interim/valuation_rebuild_queue.csv \
  --signal-date YYYY-MM-DD
python3 scripts/build_a_share_core_valuation_pool.py --signal-date YYYY-MM-DD
```

第 1 步不得跳过；披露窗未关的报告期由脚本强制重取并在结尾告警，除权事件库随第 1 步同批刷新。

第 5.5 步只报异常不改数，**「严重」级须逐条处置后才继续**。任一步失败即停止；不得把旧估值表上的校验通过当成新带已生效。完成后核对模型带、档案、估值表和核心池的带值与日期一致，持仓侧带的成员与候选侧生产带一致。校验失败行冻结新增买入，修复后再物化。

仅刷新每日现价和展示档位时运行：

```bash
python3 scripts/build_a_share_core_valuation_pool.py \
  --md-only --quotes fetch --signal-date YYYY-MM-DD
```

### 6.8 海外关注清单

港股、美股和韩股只作为观察附表，不写入 A 股核心池，也不进入 §9.3。质量判断沿用 §5，估值遵守价格独立、证据改带和可证伪原则；交易货币不得跨市场直接比较（`P/V` 可以）。

**估值口径与 A 股相同**：合理估值按 §6.5.2.3 的 ROIC 口径由三大报表重算（`build_historical_valuation_bands.py --value-model roic` 的生产参数逐项同式），最新季报／中报按「最近完整财年＋本期累计−上年同期累计」合成 TTM 作为当前观察点，年度历史仍用于 ROIC0、增量 ROIC 与再投资率。r = 美债 10Y ＋ β×经营地 Damodaran ERP（β 按档与 A 股同表），报表币按 `data/reference/overseas_valuation_inputs.csv` 的汇率折到交易币、ADR 按普通股数折算；金融企业（伯克希尔）ROIC 不适用，沿用档案带并标明；ROIC 路径被拒或无三表源（韩股、未申报公司）一律「无法估值」，旧档案带只作参考文本。三表来源：美股 SEC XBRL companyfacts、港股东财 HK F10；6-K／境外发行人未进入 companyfacts 的季报按官方财报维护 `data/reference/overseas_statement_overrides.csv`（原始文件不入库，提取结果 `data/interim/overseas_roic_years.csv` 入库）。

```bash
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --apply
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --check-only
python3 scripts/fetch_overseas_statements.py --as-of YYYY-MM-DD [--refresh] # 年报＋最新季报 TTM → overseas_roic_years.csv
python3 scripts/build_overseas_roic_bands.py --as-of YYYY-MM-DD            # ROIC 口径合理估值 → overseas_watchlist_valuation.csv ＋ README「ROIC 口径估值」节
python3 scripts/build_a_share_core_valuation_pool.py --md-only --quotes fetch --signal-date YYYY-MM-DD
```

阅读版 `000_a_share_core_valuation_pool.md` 两表列：代码／名称／质量／参考分／估值／估值路径／现价／**合理估值 V**／**`P/V`**／估值时间／估值事件（合理价区间、空间、策略标签、PE、PB 只在 CSV）。表前只保留字段含义与交易边界；估值路径只显示方法名，不带章节号或口径注记。

**回购与分红的处理**：估值只看「可分配现金 = NOPAT × (1 − 维持增长所需留存)」，分红与回购同属可分配现金、不区分、不另按股数缩减重复计量，未来回购计划不进模型。海外引擎每股 NOPAT 锚 = 各年 NOPAT ÷ 最新稀释股数（增长态取最新、否则近 3 年中位），周期守卫比较 NOPAT/(母公司权益＋累计回购)；A 股引擎按 §6.5.1 的每股锚口径，两侧差异成文（OI-082）。A 股分红按 §11.4 除权归一化处理，银行股利折现只计现金股利。

海外最新定期报告只认 `data/reference/overseas_report_evidence.csv` 的公司 IR／交易所／监管申报证据。附表 `估值时间`、清单 `valuation_reviewed_at`／`evidence_available_at`／`last_report_date` 均写该报告的公开可得日，`估值事件` 写报告类型；不得写脚本运行日。`next_report_date` 只作预期提醒，过期日历日期未获官方证据确认时不得当作已披露，且必须报“待核验”并核对公司官方业绩页。报告日、证据日、带、档位和不可买状态维护在 `data/processed/overseas_watchlist_valuation.csv`。

## 7. 阶段三：披露与事件滚动更新

### 7.1 证据同步与更新队列

先刷新队列读取的两个证据源：

```bash
python3 scripts/fetch_a_share_report_disclosures.py --report-date <当前报告期末> \
  --output data/interim/a_share_report_disclosures.csv
python3 scripts/fetch_a_share_earnings_forecasts.py --report-date <当前报告期末> \
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
  --funds <现金加可用授信>
```

`--nav` 决定一档；`--funds` 决定当天实际可执行预算。不给 `--nav` 时只生成行情和 `P/V`，不生成执行清单；不给 `--funds` 时不做换仓。产物：`daily_buy_candidates.csv`（行情、候选侧 `model_pv` 与持仓侧 `hold_pv`）、`daily_sell_plan.csv`（§9.3.2 第 4 步卖出清单）、`daily_entry_plan.csv`（第 5 步买入清单）、`daily_cooldown_state.csv`（§9.3.3 计数器）。持仓不在核心池内的票由扫描器另取行情（交易所按证券名单），只进卖出侧。`--as-of` 是信号日（最近收盘日）；模型带的证据截止由同一信号日自动推导。

### 8.3 必需量

| 量 | 口径 |
| --- | --- |
| 收盘 | T 日收盘，不存在盘中版本 |
| MA20、MA60 | 前复权收盘简单移动平均（回测 `adjusted_moving_averages` 同基：按除权事件折回当日口径） |
| `P/V` | 未复权现价 ÷ §6.5 当前生产带中值；候选侧读生产带、持仓侧读持仓侧带（§6.5.2.3），两侧各列 |
| 相关性 | 近 252 个交易日日收益率皮尔逊相关；只对合格候选、在手持仓和已选候选按需计算 |

除上表判定所需量外不再计算或展示其他量价指标。

日线取数只有一份实现（`screen_daily_volume_price_signals.fetch_daily_rows`：东财主源、腾讯备源、北交所走腾讯）；§11.3 持仓跟踪的收盘与 MA60 同用它取数。

### 8.4 故障与缺口

`--since auto` 自动检出上次扫描日（读上一份 `daily_buy_candidates.csv` 的 `trade_date`），报告缺口区间的交易日数、区间涨跌与最大放量倍数。扫描为零行或行情失败达到一半时非零退出，当日结果不可用；低于一半按停牌或个别数据缺失逐行标注。扫描写入决策日志的只有结论行：取数异常（`data_error`／`insufficient_price_history`）与 §7.5 复核冻结（`review_frozen`）；正常行情行不写。

## 9. 每日执行与交易规则

### 9.1 六步定序

信号口径与执行时点只认 §9.3.1。执行日价格变化不重算信号日合格集；停牌或执行日新增 §7 事件时跳过该票并重新复核。

1. **同步证据**：按 **§7.1** 跑完「两个取数脚本 ＋ 队列重建」三条命令（**只重建队列不算同步证据**）；运行 §7.5.2 财报日价格背离检查；核查 §7.4 的每日范围。
2. **更新估值与档位**：队列出现 `valuation_review_needed` 时**当晚以同一信号日执行 §6.7**（含其第 1 步的逐季财务刷新）；随后重建队列，再刷新核心池阅读版和当日档位。
3. **取行情与生成买入计划**：运行 §8.2，确认净资产、可用资金、持仓和模型带均已加载。
4. **跟踪持仓与公司行动**：运行 `track_holdings_daily.py --as-of`；先按 §11.4 用 `apply_holdings_corporate_action.py` 处理除权除息并登记台账，再检查止损、公告与估值。
5. **形成执行清单**：由第 3 步的扫描器按 §9.3.2 先卖后买生成 `daily_sell_plan.csv` 与 `daily_entry_plan.csv`，四张表即使为空也必须显示；止损行只列候选，T+1 尾盘按现价对当日生效线复核后执行，其卖出款不计入当日买入预算。
6. **输出与留痕**：回复用户，并将同一内容置顶写入 `data/processed/000_daily_scan_log.md`；成交后按 §11.5 回写。

当日无估值更新时可以省略 §6.7 重建，但必须明确写“当日无估值更新”。

### 9.2 输出格式

```text
## 每日扫描 YYYY-MM-DD（信号日；执行时点见 §9.3.1）

### 一、当前持仓
| 名称 | 层级×现档 | 参考分 | 收盘 | 合理价区间 | 空间 | P/V | 动作 |

### 二、执行清单（时点见 §9.3.1）
1. 一档金额
2. 合格集及相关性跳过项
3. 卖出清单
4. 买入清单

### 三、需人工处理
除权除息、待复核、停牌、执行日新增事件和数据缺失
```

合格集为空时写“今日无合格标的，持币”，不得放宽阈值或用盘面事实补位。

### 9.3 唯一交易口径

输入边界：名单只来自 §5，合理价只来自 §6，行情只来自 §8。账户级只剩个人投资体系 §4 的两条外生硬约束，不在本节重复。

#### 9.3.1 当前参数

| 项 | 当前唯一取值 |
| --- | --- |
| 候选池 | 当日 `worth_attention` |
| 估值 | 候选侧（买入线、排序、换仓触发候选）读 §6.5 当前生产模型带；持仓侧（减持、换仓来源）读 §6.5.2.3 持仓侧带；`P/V = 收盘 ÷ V` |
| 买入线 | `P/V ≤ 0.9343` |
| 新建仓走势 | T 日 `收盘 > MA20 > MA60` |
| 已有持仓加仓走势 | `MA20 > MA60`，不要求收盘高于 MA20 |
| 排序 | `P/V` 升序，资金用尽即停 |
| 相关性 | 与在手及已选标的近 252 日相关性 `≤ 0.70`；超限跳过，最多下扫 40 名。两侧同取扫描当日前复权K线、按交易日对齐；重叠收益率不足 120 个时无值，放行并在报告列名单 |
| L3 战术闸门 | `quality_tier = L3` 且分层表 `tactical_thesis` 为空或判「无／暂无／不可买」者不进合格集（新建仓与加仓同，持仓照常跟踪与减持）；战术理由的判据、里程碑写法见 `docs/Ashare_quality_rubric.md` §8，补判为条件式后自动重入。回测不复现（成文差异） |
| 单次买入 | 当日净资产 `N × 5.0%` |
| 持仓只数上限 | 无 |
| 单票机械上限 | 单票市值 ÷ 当日净资产 `N` ≥ 60% 时不再加仓；不足 60% 时本档只补到 60%（可小于一档，按一手向下取整，不足一手跳过）。**只挡加仓，不触发任何卖出**：已有持仓因上涨越限不回削，减持／涨幅减持／换仓／止损各按本表规则；新建仓（一档 5%）与换仓目标（必为未持仓票）不受影响。按信号日收盘市值与当日 `N` 判 |
| 减持 | 持仓侧 `P/V ≥ 2.4257` 且 `收盘 < MA20`，减一档 |
| 涨幅减持 | 收盘较持仓均价涨幅 `≥ 125%`（收盘 ≥ 均价 × 2.25）且 `收盘 < MA20`，减一档；持仓均价 = 买入按股数加权、减持不变、除权按 §11.4 折算（持仓表 `cost_basis`） |
| 换仓 | 只由**未持仓**的合格候选触发（已持仓候选加仓不触发），按 `P/V` 升序逐个判：可用资金不足一档时先换出**满足涨幅减持条件**的持仓一档（涨幅最大者，不比 `P/V` 边际）；否则该候选（候选侧 `P/V`）须比最贵的弱势持仓（持仓侧 `P/V`）至少低 `0.1437`，且被换出持仓 `收盘 < MA20`；卖一档、买一档。卖出款不定向给触发候选，与其它可用资金一并按 §9.3.2 第 5 步 `P/V` 升序买入 |
| 止损 | 锚 = 零股建仓时的成交日 MA60；**生效止损线 = min(锚, 当日 MA60)**——均线下移时跟随下移、上移不抬线；执行时点（尾盘 14:45-14:55）现价跌破当日生效线即**当日**整仓清空 |
| 止盈 | 无 |
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

配置文件只写相对 `BASE` 的变化，不手抄完整基准命令。回测宇宙固定读取 `data/processed/pit_attention/panel_moat_bank_v6b.csv`，估值状态固定读取 `data/processed/a_share_daily_states_adopted.csv`（候选侧）与 `data/processed/a_share_daily_states_hold.csv`（持仓侧，`--hold-states`：减持线、换仓来源、簇内升级与 T+1 换仓确认读它）。

回测基准的融资口径：本金 300 万；授信 = 净资产 × 66.6%，不设金额上限；强平线 130%；融资年利率 3.5%；资金顺序按 §10.2（授信每日按净资产重定，所有卖出款先偿还超出额度的负债，负债回到额度内才可买入，换仓与买入按现金＋剩余授信判）。实盘与回测同口径。

回测的执行与公司行动口径：T+1 成交日无价（停牌、末日）该笔跳过、不回落信号日成交（与 §9.1 同）；除权按 §11.4 同式折算，配股全额认购、认购款不足部分计融资负债；现金红利按除权日计入现金（不模拟到账日，成文差异）；差别化股息税按卖出时持有期对所卖股份持有期内已收现金红利结算（≤1 个月 20%、≤1 年 10%、>1 年免，FIFO；送股面值部分不计，成文差异）；差异化分派按公告每股派息（成文差异）。

#### 9.3.2 每日机械顺序

1. 计算全池当日 `P/V`，排除不在名单、`review_pending`（回测不复现，成文差异）与 L3 无战术理由（§9.3.1 L3 战术闸门）股票。
2. 形成走势合格集：新建仓与加仓分别使用 §9.3.1 的条件。
3. 按 `P/V` 升序做相关性过滤。
4. 先卖：
   - 执行时点现价跌破当日生效止损线（§9.3.1 止损行）：当日整仓清空，且不再走当日其他路径。
   - 触发减持条件（`P/V` 行或涨幅行）：减一档。
   - 已移出 `worth_attention`：每日减一档直至清空，不加走势条件。
   - 未持仓合格候选想买但资金不足且满足换仓条件（已持仓候选加仓不触发）：先减持涨幅 ≥125% 且弱势的持仓一档（涨幅最大者），否则减持最贵的弱势持仓一档；同一持仓每日至多换出一档，无其他卖出源即停止换仓。触发候选随后被相关性过滤挡下时不豁免，卖出款顺位流向下一名。
   - 任何减档后的余仓不足一手时清空。
5. 后买：对过滤后的合格集按 `P/V` 升序逐个买一档（含换仓卖出款，不定向给触发候选），按手向下取整，可用资金耗尽即停。
6. 同日对冲：同一只股票当日买卖并存时按较小者抵消，只执行净额，被抵消部分不计佣金、印花税与股息税。适用减持、涨幅减持与换仓；出名单与止损为强制退出，不抵消，同日买入清单里出现该股即在报告显式提示。

股数以 T 日收盘估算；T+1 按实际成交价调整手数，一档金额不变。

#### 9.3.3 高价股比例冷却

一手金额大于一档时仍成交一手。令 `x = 一手金额 ÷ 一档`，随后跳过 `round(x) − 1` 次该票的合格机会；买入、减持和换仓共用同一计数器。冷却按合格次数，不按自然日。计数器持久化在 `data/processed/daily_cooldown_state.csv`，扫描器每次生成执行清单时读入、消费、回写；同一信号日重跑从 `remaining_before` 重算，`--as-of` 早于文件 `applied_trade_date` 的历史重放不应用也不回写。

#### 9.3.4 现有持仓衔接

不做一次性组合重构。在名单内的持仓继续按 §9.3 加减；已出名单的逐档清仓；不因持仓只数多或被动上涨形成高权重而单独卖出。

#### 9.3.5 建仓止损的记录与复位

按 §9.3.1 的止损口径，由零股建仓时把实际成交日的止损基准（**锚**）写入 `entry_stop_price`。加仓不重设，清仓后重新建仓才重设；除权除息按 §11.4 同因子调整锚（回测 `apply_corporate_actions` 同式折算）。

**生效止损线每日取 `min(锚, 当日同周期均线)`**：锚永不上移，均线跌到锚下时生效线跟随均线；执行时点现价低于生效线时当日即清，不引入等待日。持仓表只存锚不存周期（§11.2 五列），`track_holdings_daily.py` 统一按当日 MA60（前复权口径，§8.3）计算生效线，收盘跌破时提示次日尾盘按当日线复核。锚恒为成交日 MA60；成交日取不到 MA60（停牌回落、上市不足 60 根）时锚退成交日 MA20、生效线按同周期均线判，MA20 锚持仓按同周期人工复核。

## 10. 风险过滤与账户防护

### 10.1 买入过滤器

以下任一命中即跳过并顺位补下一名：

1. 不在 `worth_attention`。
2. thesis 已证伪，或存在造假、审计、资金占用与重大治理风险。
3. `buy_blocked = review_pending`。

第 3 项只挡新增买入，不主动触发卖出。

### 10.2 账户级防护

账户级只有两条外生硬约束——券商授信额度与 130% 强平线，口径见个人投资体系 §4。授信额度 = 当日净资产 `N` × 66.6%，不设金额上限；融资负债读 §2 的账户快照台账。每日实际可用资金为：

```text
现金 + max(0, N × 66.6% − 当前融资负债)
```

该值作为 §8.2 的 `--funds`。用户回报券商可用保证金时，`--funds` = 券商可用保证金 + 现金（现金另计，用户未报现金即记 0），不按上式估算；上式只在未回报时使用。负债超过授信额度（券商可用保证金为 0 或上式为负）时不可新增买入，卖出款先偿还超额负债。触及账户级阈值时在当日报告显式提示；未触及时不重复展开。

### 10.3 策略收益跟踪

策略基准日 2026-08-28，基准净资产 = 该日账户快照 `net_assets_cny`（`strategy_base_net_assets_cny` 列）。账户快照每日登记：

| 列 | 取值 |
| --- | --- |
| `external_cash_flow_cny` | 当日外部现金流：入金为正、出金为负，无则 0 |
| `strategy_return_pct` | `(N − 基准日后累计外部现金流) ÷ 基准净资产 − 1`，百分比保留两位 |
| `account_peak_net_assets_cny` | 基准日起 `N − 累计外部现金流` 的最高值，基准日取基准净资产 |
| `drawdown_from_peak_pct` | `(N − 累计外部现金流) ÷ account_peak_net_assets_cny − 1` |

基准日前各行的峰值与回撤列只存历史数据，不参与计算。当日报告账户段列出策略收益率与策略期回撤。

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

逐票检查当日公告、披露、重大事项、产业和竞品信息，并显示现档、合理价、空间、`P/V`、MA20、MA60、生效止损线与是否命中、减持／涨幅减持是否命中。行情缺失必须标为“数据缺失”，不得显示为“持有”。收盘、MA20 与生效止损线的 MA60 走 §8.3 的同一份取数实现，减持命中判定与扫描器同一实现（`holding_trim_signal`）；`P/V` 读持仓侧带，与候选侧不同时并列显示；生产带的证据截止与扫描器同由信号日自动推导。

### 11.4 除权除息

除权日按交易所除权参考价同一公式调整：

| 分派 | 带、止损价与 `cost_basis` | 股数 |
| --- | --- | --- |
| 每股现金红利 `D` | 原值 `− D` | 不变 |
| 每 10 股送转 `k` 股 | 原值 `÷ (1+k/10)` | `× (1+k/10)` |
| 每 10 股配 `r` 股、配股价 `p` | `(原值 + r/10 × p) ÷ (1+r/10)` | 认购则 `× (1+r/10)`、付 `股数 × r/10 × p`；不认购不变 |
| 并存 | `(原值 − D + r/10 × p) ÷ (1 + k/10 + r/10)` | `× (1 + k/10 + r/10)` |

**带的调整由建带链机械维护**：生产带文件在 §6.7 第 4 步末段按「带的公告日之后的除权事件」归一化到现价口径（现金＋送转＋配股；银行与保险走股利折现、分子按财年归属，不参与减项），回测逐日状态同一规则；调整持续到公告日晚于除息日的下一份报告接管为止，重建不抹掉。事件库 `data/raw/corporate_actions/a_share_corporate_actions.csv` 的分红送转取东财、配股取新浪配股表（`rights_ratio`／`rights_price` 列），随 §6.7 第 1 步刷新。**持仓表按事件落地**：`entry_stop_price` 是历史价格，须按上表调整并永久保留；`cost_basis` 与股数同批调整。差异化分派按交易所价格口径处理。

```bash
python3 scripts/apply_holdings_corporate_action.py --as-of YYYY-MM-DD --code <代码>            # 事件取事件库当日行，缺则东财当日接口
python3 scripts/apply_holdings_corporate_action.py --as-of YYYY-MM-DD --code <代码> --cash <每股现金> --ratio <每股送转>   # 差异化分派：显式给价格口径
```

执行即写回持仓表并登记 `data/processed/holdings_corporate_actions_applied.csv`（同一代码＋除权日只登记一次，二次执行被拒绝）；配股缺省认购，`--no-subscribe` 不认购。跟踪器的检出按台账区分「已处理／未处理」（现金送转读东财当日接口，配股读事件库当日行），并对近 30 日事件库有除权而台账无登记的持仓提示疑似漏调；当日报告必须显示“当日持仓除权除息：无/名单”。

### 11.5 成交回写

用户确认成交后：

1. 更新持仓股数与成本；清仓删除该行。
2. 由零股建仓时按 §9.3.5 写入止损价；加仓不改。
3. 决策日志追加 `execution_record`，记录方向、股数、成交价、当日 `P/V` 和对应规则。
4. 次日自动纳入跟踪。

## 12. 改参数与回测验证

参数依据与全部历史读数只查 `docs/Ashare_backtest_log.md`。工作流正文只保存 §9.3.1 当前选择。

### 12.1 验证纪律

新候选先登记轨道，登记在跑数之前完成，跑完不得更换：

* **轨道 A（机制修复）**——与本文件成文标准、实盘可执行性或 `docs/000_personal-investment-system-v1.zh.md` 原则不符者。轨道 A 的依据须指向本文件的具体条款或可复现的实盘差异，指不出的改走轨道 B。采纳依据为机制正确性，回测只作护栏：第 2 款的闸门与否决不得触发，主读数损失不超过 1pp。
* **轨道 B（收益动机）**——其余全部，按第 2、3 款的决策读数判。

两条轨道都按以下顺序验证：

1. 先确认数据、股票池有效期、复权、手续费、整手、融资和执行延迟均与 `BASE` 一致。
2. 预先按预计实盘持有期选收益主窗口，缺省取 5 年。滚动窗口**月末锚定**：窗口末日 = 每个自然月最后一个交易日，首日 = 60 个月前同月末，年化按实际日历年数，回撤与 Sharpe 用窗口内逐日净值。标准 23 个半年起点上**决策读数只有四项**：主读数 = 滚动 5 年 CAGR 中位的配对差中位与正号数；坏情形 = 滚动 5 年 CAGR P25（**起点内**月末窗口的分位；P10 不作决策）的配对差与正号数；闸门 = 滚动 5 年回撤中位不得变深超过 3pp；否决 = 滚动 5 年负收益窗口占比由 0 转正（过半起点）。其余一律只描述不排序：滚动 5 年最差值、滚动 3 年 CAGR／Calmar／Sharpe、滚动 10 年 CAGR（只在够长的起点上有值，空≠差）、逐年收益分布、全期 CAGR／最大回撤／Calmar／Sharpe。不得看完结果再换主窗口或换读数。同时报告换手与平均仓位。两层分位不要混：符号数是 23 个起点层，P25／最差是起点内窗口层。
3. 报逐起点配对差中位和正号起点数，不比较两个独立中位数的差。每轮扫描同时出第二张对照表：统一剔除 `BASE` 前五大赢家（`BASE` 臂 2011-11-01 起点全部闭合周期按代码汇总 `proceeds − invested` 的前五名，取 summary `前五赢家` 列；`--exclude-codes` 从全部臂统一剔除，不改面板），Δ 对去赢家 `BASE` 配对；`sweep_backtest_configs.py` 缺省自动跑第二遍，`--no-ex-top5` 只用于纯补跑。去赢家读数不单独作采纳依据。
4. 参数至少扫描相邻区间，优先选择宽平台，不选择单点峰值；±0.15 个百分点以内视为噪声。
5. 增加互不重叠的持有期或逐年检验；共享终点的多个起点与重叠滚动窗口不视为独立样本。
6. 检查可执行性、幸存者偏差、未来信息和多重比较；绝对收益不当作未来预期。
7. 只有第 1~6 款通过、第 9~11 款读数齐备且用户裁定后，才修改 §9.3.1、生产常量和回测 `BASE`。
8. 实验过程写入回测 log；最终版本变化写入 changelog；当前操作只写回本文件。
9. 信号层三表：`scripts/experimental/selection_edge_audit.py`（边际选择检验、排序信息量、换仓方向性；回测须带 `--candidate-log` 与 `--trade-log`）与 `scripts/experimental/panel_tier_forward.py`（`P/V` 分档前向回报）。采纳候选在候选臂与 `BASE` 上各跑一遍并报差；另每季在 `BASE` 上重算一遍作不变量检验。各表报逐日配对差中位、为正日数与逐年同号年数。换仓方向性一表须同报 `scripts/experimental/swap_regime_control.py` 的四表对照（面板层 `P/V` 信息量、合成换仓、`P/V` 匹配对照、样本独立性），匹配对照的容差至少取 ±0.04／±0.10／±0.15 三档、只报符号稳健的读数；该表的样本量按不同 `(源, 标的)` 配对数计，不按日数；只有与合成换仓反号的年份计入机制层结论。三表不进第 2 款的决策读数，读数写入回测 log。
10. 采纳候选报 `scripts/experimental/delta_attribution.py` 的前三只净额占比；超过 100% 者不作采纳依据。
11. 引用正读数时同报本族已试臂数，按 `data/processed/backtest/scan_summaries.csv` 的扫描标签计。

历史面板 `effective_from` 与 `effective_to` 均为有效期边界，结束日包含在内。禁止把区间起点当成完整快照，也禁止手工修改面板 CSV；名单变化先改判定源，再运行装配脚本。

换估值口径或换宇宙做 A/B 时，**三条线必须一起重解到同一在册合格面**（`scripts/experimental/align_buy_line.py`），否则比的是两条不同宽度的闸门。现行三线 **候选侧买入线 0.9343／持仓侧减持线 2.4257／换仓边际 0.1437**：买入线对候选侧状态下侧合格面 17.775%、减持线对持仓侧状态上侧面 30.025%（候选侧同面解 2.4671），506,118 个在册观测，保留四位小数、不取整。现行基准（`BASE`：候选侧 `a_share_daily_states_adopted.csv`＋持仓侧 `a_share_daily_states_hold.csv`、授信 66.6%、单票上限 60%、T+1 无价跳过、股息税、换仓源同日不重复、同日买卖对冲、配股事件，月末锚定口径）在册读数：**滚5 中位／P25／最差 64.42／54.06／25.49、滚5 回撤中位 47.8、滚5 Calmar 1.33、滚5 Sharpe 1.17、负窗口占比 0；滚3 中位 51.90；年化中位 48.12、最大回撤中位 59.2、Calmar 0.79、Sharpe 0.90、换手 4.39、逐年中位 46.15、逐年最差 −25.0**。配对差一律相对现行基准读数，读数不跨纪元迁移；各纪元的三线解与在册读数只查 `docs/Ashare_backtest_log.md`。

当前参数是取舍前沿上的一点，不是三条标准同时占优的峰；援引本基准时说清按哪条标准选的，不称「最优」。

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

当前版本只认第 1 行。版本变化记入 `docs/Ashare_workflow_changelog.md`，回测依据记入 `docs/Ashare_backtest_log.md`；完整旧正文可从 Git 历史恢复，不复制回本文件。

2026-08-19 以前的历史记录（changelog、回测日志、扫描日志、决策日志）使用旧章节编号，新旧对照表见 changelog v4.19 行。
