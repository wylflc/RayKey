# A股选股-估值-量价操作流程 v4.11

> 本文件只保留当前生效的操作指引。第 1 行是唯一版本真值，供 `scripts/workflow_decision_log.py` 写入决策日志。
>
> 历史版本变化见 `docs/Ashare_workflow_changelog.md`；回测过程、参数比较与被否决方案见 `docs/Ashare_backtest_log.md`；已知未修缺陷见 `docs/Ashare_workflow_open_issues.md`。正文不保存历史参数、实验读数或退役机制。

## 0. 任务路由

| 请求 | 执行章节 | 主要入口 |
| --- | --- | --- |
| 今日 A 股每日扫描 | §9.1、§9.7、§11 | `screen_daily_volume_price_signals.py`、`track_holdings_daily.py` |
| 今日该买、加、减、换什么 | §9.7 | §9.7.1 参数表与 §9.7.2 顺序 |
| 今日持仓跟踪 | §11 | `track_holdings_daily.py --as-of` |
| 季度全市场质量审查 | §5.1-§5.4 | `build_quarterly_quality_review_queue.py` |
| 对 `worth_attention` 做 L1-L3 分层 | §5.7-§5.8 | `a-share-quality-tiering` 工作流 |
| 更新估值与核心池 | §6 | §6.7 估值重建链 |
| 财报披露后的滚动更新 | §7 | `build_report_update_queue.py` |
| 单票研究 | §5 → §6 → §9.7 | 逐层判断，任一层否决即止 |
| 修改估值、交易规则或回测参数 | §12-§13 | `sweep_backtest_configs.py` |

所有可复核结论均按 §2 写入决策日志。买卖机制只认 §9.7；账户级风险与行为红线只认 `docs/000_personal-investment-system-v1.zh.md`。

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
3. `P/V` 与走势条件按 §9.7 机械产生执行清单，不临时加入主观快速通道。
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
| 当前生产模型带 | `data/processed/a_share_pool_model_bands_adopted.csv` |
| 核心估值池 | `data/processed/a_share_core_valuation_pool.csv` |
| 核心池阅读版 | `data/processed/000_a_share_core_valuation_pool.md` |
| 持仓 | `data/processed/a_share_holdings.csv` |
| 账户快照与授信台账 | `data/processed/portfolio_account_snapshot.csv`；`credit_line_cny` 列是券商授信额度的唯一登记处 |
| 每日买入计划 | `data/processed/daily_entry_plan.csv` |
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
| `garbage` | 仅因坐实治理灾难或结构性绝望行业而永久排除的公司 |
| L1/L2/L3 | §5.7 的业务质量分层；不直接决定买入资格 |
| 合理价 `V` | §6 当前生产带上下沿的中值 |
| `P/V` | 未复权现价 ÷ `V`，交易规则使用的估值比率 |
| 空间 | `V ÷ 现价 − 1`，仅作阅读展示 |
| 合格集 | 通过 §9.7.1 买入线、走势条件、冻结与相关性过滤后的股票，按 `P/V` 升序 |
| 一档 | 按 §9.7.1.1 从当日净资产计算的单次交易金额 |

## 4. 总流程

```text
A股证券名单 ∪ 财报中出现的A股证券
  → §5 三类初筛
  → 对 worth_attention 做 L1-L3 分层
  → §6 建立并校验生产模型带
  → §7 根据披露与事件滚动复核
  → §8 取得收盘、MA20、MA60、P/V、252日相关性
  → §9.7 先卖后买，生成 T+1 尾盘执行清单
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

python3 scripts/build_quarterly_quality_review_queue.py \
  --market A_SHARE \
  --as-of YYYY-MM-DD \
  --universe data/raw/a_share_securities.csv \
  --attention-triage data/processed/a_share_attention_triage.csv \
  --previous-tiers data/processed/a_share_watchlist_quality_tiers.csv \
  --output data/interim/a_share_quarterly_quality_review_queue.csv
```

证券名单必须保留来源字段并生成不可变日期快照。新股若披露不足，先进入 `boundary_pending`，不得因资料少判为 `garbage`。

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
| 商品与资源 | 同时要求稀缺/配额、成本曲线和规模/储量；仅有其中一项不足以入选 |
| 资本密集周期制造 | 结构整合、技术、规模或准入壁垒已使替代客观困难时可以入选；景气本身不算壁垒 |
| 客户集中 | 区分可竞争买方与结构性单一买方；后者须有长认证、准入锁定和稳定长期 ROE，前者须证明能力可跨客户迁移 |
| 受困或 ST | 未坐实造假时按竞争力判断；控制权已更换且责任人出清时允许回到 `boundary_pending` 复核 |

具体行业校准证据只保存在 `docs/peer-group-calibration/`，执行时用来校验本节规则，不另立阈值。

#### 5.4.7 状态迁移

| 迁移 | 触发 |
| --- | --- |
| `worth_attention → boundary_pending` | 持久优势证伪或资本复制测试不再通过 |
| `worth_attention → garbage` | 坐实治理灾难或行业被证实结构性绝望 |
| `boundary_pending → worth_attention` | 财报、订单、客户验证、产品、重组或行业结构等硬触发后重新通过测试 |
| `boundary_pending → garbage` | 坐实治理灾难或结构性绝望 |
| `garbage → boundary_pending` | 仅限原证据被权威信息推翻、责任人出清，或子赛道被证明结构不同 |

质量分层不能改变 `attention_class`。任何迁移均写决策日志；纠错必须关联旧 `decision_id`。

### 5.5 复核队列条件

满足任一条件进入队列：新上市；新报告晚于上次复核；原 L1/L2；L3 出现经营或技术改善；`boundary_pending` 出现硬触发；关键利润率、现金流、负债、研发或增长发生重大变化；发生诉讼、处罚、审计或控股股东风险。

`garbage`、无硬触发的 `boundary_pending`、以及只有价格或传闻变化的公司不进入队列。

### 5.7 L1-L3 质量分层

| 层级 | 判定 |
| --- | --- |
| L1 强护城河 | 通道 A：Q2 ≥ 82 且 Q1 ≥ 66；或通道 B：Q1 ≥ 80 且 Q2 ≥ 78；同时不存在成立的中/高概率侵蚀路径 |
| L2 中护城河 | 未过 L1，且未触发 L3；这是默认层级 |
| L3 弱护城河 | 被更强同行全面覆盖且无不可替代利基；或 Q2 < 66；或 Q1 < 60 且 Q2 < 72 |

评分细节和判例见 `docs/Ashare_quality_rubric.md`。参考分只用于同层排序：

```text
参考分 = Q1×0.25 + Q2×0.40 + Q3×0.20 + Q4×0.15 − 报表可信度扣分
```

硬规则：

1. 只对 `worth_attention` 评分；价格、估值、市值、流动性和当前景气不入分。
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

对全部 `worth_attention` 公司维护估值带。估值只生成合理价 `V`；买卖资格由 §7 的冻结状态和 §9.7 决定。

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
2. 财务数据按公告日 `available_at` 生效，禁止用报告期末代替可得日。
3. 季报财务为累计口径；单季值用同年累计差分，TTM 用最近四个单季求和。
4. 一致预期使用逐份研报归母净利润中位数，覆盖少于三家时不得采用；禁止混用送转前后的研报 EPS。
5. 预告与快报只有在公告已发生、尚未被正式报告取代且报告期已实质走完时进入锚；快报优先，区间取中值。
6. 跨字段比率必须使用同一披露口径；字段缺失时整体退回上一套已披露口径，不拼接半新半旧的数据。

### 6.5 当前估值方法

#### 6.5.0 策略标签

策略标签只用于研究分类和展示，不选择生产估值模型。标签定义以个人投资体系 §5 为准；所有 A 股生产带仍统一走本节模型。

#### 6.5.1 唯一生产模型

非银行使用 ROIC/FCFF 内在价值模型：NOPAT、投入资本、增量 ROIC、再投资率、WACC、增长衰减和净负债共同生成每股价值。生产参数由 §6.7 的建带命令唯一给出，不在逐票档案临时改写。

银行使用：

```text
V = 近12个月每股现金分红 ÷（十年期国债收益率 + 2%）
```

所有正常模型带均为 `[0.90×V, 1.10×V]`，中值即 `V`。策略标签只作展示与同类研究，不参与生产估值计算。

#### 6.5.7 逐票估值档案

##### 6.5.7.1 P/V 与带宽

正常生产带的中值必须等于模型内在价值，生产 `P/V` 与回测 `valuation_ratio` 使用同一分母。

##### 6.5.7.2 模型计算

模型计算统一由 §6.7 命令完成；档案不得覆盖模型参数或为希望得到的档位反推输入。

##### 6.5.7.3 生产带落地

`data/processed/a_share_pool_model_bands_adopted.csv` 是生产模型带唯一来源。逐票档案只承载研究结论和当前带；`apply_model_bands_to_dossiers.py` 只覆盖带相关字段，保留 `key_metrics`、`review_triggers`、高频指标和研究备注。

送转后必须把报告期口径的每股价值按股本因子折算到现价口径。生产 `P/V` 与回测 `valuation_ratio` 必须逐位一致。

##### 6.5.7.4 手工例外

只有两类公司可以保留逐票手工带：

1. 模型无法计算：NOPAT、EPS 或归一化 ROE 不满足模型定义。
2. 最新模型带过旧：重组、资产注入、分拆或借壳使旧财务主体不可比。

手工带必须使用前瞻一致预期或归一化利润，倍数必须可推导并记录来源，能够双向支持买入与减持；不得因“看起来更合理”绕过模型。模型重新可算后立即切回生产带。

### 6.6 人工复核职责

人工只处理：模型不可估原因；主体不可比；新证据是否触发重算；手工例外的锚与来源；校验失败行。正常公司不逐票选择模型、倍数或带宽。

档案必须保留证据事件、证据可得日、关键指标、高频指标、下一复核点和可证伪触发。带变动后重渲染逐票 README。

### 6.7 估值重建链

以下顺序是当前唯一生产路径。重建全历史模型带属于重作业，必须独占运行。

```bash
# 1. 刷新财务输入。**两份缺一不可**：
#    逐季财务是模型的 TTM 锚（每个扫描日都可能变），三大报表只有年报（4 月后到次年才动）。
python3 scripts/fetch_a_share_quarterly_financials.py --as-of YYYY-MM-DD --since <当前报告期末>
python3 scripts/fetch_a_share_financial_statements.py

# 2. 构建 ROIC 带与逐日状态
python3 scripts/build_historical_valuation_bands.py --all --value-model roic \
  --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 --since 2002-01-01 \
  --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --out-bands data/processed/roic_bands.csv \
  --out-daily data/processed/roic_daily_raw.csv

# 3. 银行改用股利折现并生成采纳逐日状态
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_adopted.csv \
  data/processed/roic_daily_raw.csv \
  data/processed/roic_bands.csv

# 4. 生成池模型带并写入逐票档案
python3 scripts/build_pool_model_bands.py --as-of YYYY-MM-DD
python3 scripts/apply_model_bands_to_dossiers.py --as-of YYYY-MM-DD

# 5. 档案 → 建带卡 → 估值表
python3 scripts/build_valuation_band_cards.py \
  --tags data/interim/strategy_tag_map.csv \
  --out data/interim/valuation_band_cards.csv \
  --as-of YYYY-MM-DD
python3 scripts/apply_valuation_band_cards.py --as-of YYYY-MM-DD --quotes fetch

# 6. 校验并物化核心池
python3 scripts/validate_valuation_bands.py \
  --valuation data/processed/a_share_focus_watchlist_l1_l2_valuation.csv \
  --queue-out data/interim/valuation_rebuild_queue.csv \
  --as-of YYYY-MM-DD
python3 scripts/build_a_share_core_valuation_pool.py --as-of YYYY-MM-DD
```

**第 1 步的逐季财务是本链最容易静默过期的输入**：`data/raw/financials/<报告期>.csv` 一期一个文件，
披露窗未关时首次写下的那份必然只覆盖少数早披露公司，而残缺文件与完整文件在磁盘上无法区分。
脚本自 v4.10 起对**披露窗未关的报告期强制重取**（不再由 `--refresh` 决定）并在结尾告警，
但**跳过第 1 步仍会让整条链拿旧 TTM 重算一遍旧带**——判例：贵州茅台 2026-08-15 披露半年报，
而池内该行停在 04-25 的一季报，根因就是这一步从未进入每日流程。

任一步失败即停止；不得把旧估值表上的校验通过当成新带已生效。完成后核对模型带、档案、估值表和核心池的带值与日期一致。校验失败行冻结新增买入，修复后再物化。

仅刷新每日现价和展示档位时运行：

```bash
python3 scripts/build_a_share_core_valuation_pool.py \
  --md-only --quotes fetch --as-of YYYY-MM-DD
```

### 6.8 海外关注清单

港股、美股和韩股只作为观察附表，不写入 A 股核心池，也不进入 §9.7。质量判断沿用 §5，估值遵守价格独立、证据改带和可证伪原则；交易货币不得跨市场直接比较。

```bash
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --apply
python3 scripts/fetch_overseas_earnings_calendar.py --as-of YYYY-MM-DD --check-only
python3 scripts/build_a_share_core_valuation_pool.py --md-only --quotes fetch --as-of YYYY-MM-DD
```

海外标的的报告日、证据日、带、档位和不可买状态维护在 `data/processed/overseas_watchlist_valuation.csv`。无日历源的市场必须人工维护日期并显式显示缺口。

## 7. 阶段三：披露与事件滚动更新

### 7.1 证据同步与更新队列

**队列是消费者，必须先刷新它读的两个证据源**——只跑队列而不刷新源，等于每天拿旧证据重算一遍旧结论：

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
  --as-of YYYY-MM-DD \
  --attention-triage data/processed/a_share_attention_triage.csv \
  --tiers data/processed/a_share_watchlist_quality_tiers.csv \
  --valuation-pool data/processed/a_share_core_valuation_pool.csv \
  --forecasts data/interim/a_share_earnings_forecasts.csv \
  --report-disclosures data/interim/a_share_report_disclosures.csv \
  --output data/interim/a_share_report_update_queue.csv
```

**三个文件都必须当日重建**；任一文件日期早于扫描日即不可用。`garbage` 不进入队列。

`<当前报告期末>` 取最近一个已开始披露的报告期末（`2026-06-30` 一类）。**披露窗未关时覆盖面每天都在长**，
故不存在"抓过一次就够了"——法定截止日为一季报 4-30、半年报 8-31、三季报 10-31、年报次年 4-30。

### 7.2 质量复核触发

```text
quality_cutoff = max(last_quality_review_date, evidence_available_at)
定期报告公告日 > quality_cutoff → 进入质量复核
```

披露文件缺失时才以报告期末作降级兜底，并在队列显式标注。

### 7.3 估值复核触发

预告、快报或正式定期报告的公告日晚于 `max(valuation_reviewed_at, evidence_available_at)`，即进入估值复核，不先判断幅度是否重大。披露文件缺失时才用报告期末兜底。

### 7.4 事件复核触发

以下事件当天复核：披露；重大订单或客户认证；产品与技术兑现；并购、资产出售或控制权变化；问询、处罚或审计异常；产业政策、商品价格或竞争格局重大变化；档案列明的高频指标越过触发线。

每天必查范围：全部持仓、当日披露触发、当日通过买入线与走势条件的股票、用户点名股票。若未覆盖完整范围，必须报告实际覆盖度。

处理顺序：先更新档案证据与关键指标，再重算模型带，再完成 §6.7 下游落地与校验。重新取证后带变动不超过 2% 时只刷新证据日；超过 2% 时同时更新估值复核日与证据事件。

### 7.5 复核期冻结

估值或事件复核触发后，将 `buy_blocked` 设为 `review_pending`，冻结新增买入但继续持仓跟踪。完成复核、更新证据与复核日期并重建队列后自动解除。

#### 7.5.5 Express 复核

预告或快报原则上在下一交易日开盘前完成 express 复核；发现超期时当场补做并记录原因。

#### 7.5.6 财报日价格背离

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
  --nav <当日净资产> \
  --funds <现金加可用授信>
```

`--nav` 决定一档；`--funds` 决定当天实际可执行预算。不给 `--nav` 时只生成行情和 `P/V`，不生成买入计划。

### 8.3 必需量

| 量 | 口径 |
| --- | --- |
| 收盘 | T 日收盘，不存在盘中版本 |
| MA20、MA60 | 前复权收盘简单移动平均 |
| `P/V` | 未复权现价 ÷ §6.5 当前生产带中值 |
| 相关性 | 近 252 个交易日日收益率皮尔逊相关；只对合格候选、在手持仓和已选候选按需计算 |

量比、突破、放量分位和趋势强度只作盘面描述，不参与 §9.7 买卖判定。

### 8.6 故障与缺口

`--since auto` 自动逐日回放上次扫描后的缺口。扫描为零行或行情失败达到一半时非零退出，当日结果不可用；低于一半按停牌或个别数据缺失逐行标注。

## 9. 每日执行与交易规则

### 9.1 六步定序

信号口径与执行时点只认 §9.7.1。执行日价格变化不重算信号日合格集；停牌或执行日新增 §7 事件时跳过该票并重新复核。

1. **同步证据**：按 **§7.1** 跑完「两个取数脚本 ＋ 队列重建」三条命令（**只重建队列不算同步证据**）；运行 §7.5.6 财报日价格背离检查；核查 §7.4 的每日范围。
2. **更新估值与档位**：队列出现 `valuation_review_needed` 时执行 §6.7（**含其第 1 步的逐季财务刷新**）；随后刷新核心池阅读版和当日档位。
3. **取行情与生成买入计划**：运行 §8.2，确认净资产、可用资金、持仓和模型带均已加载。
4. **跟踪持仓与公司行动**：运行 `track_holdings_daily.py --as-of`；先处理除权除息，再检查止损、公告与估值。
5. **形成执行清单**：按 §9.7.2 先卖后买，四张表即使为空也必须显示。
6. **输出与留痕**：回复用户，并将同一内容置顶写入 `data/processed/000_daily_scan_log.md`；成交后按 §11.5 回写。

当日无估值更新时可以省略 §6.7 重建，但必须明确写“当日无估值更新”。

### 9.2 输出格式

```text
## 每日扫描 YYYY-MM-DD（信号日；执行时点见 §9.7.1）

### 一、当前持仓
| 名称 | 层级×现档 | 参考分 | 收盘 | 合理价区间 | 空间 | P/V | 动作 |

### 二、执行清单（时点见 §9.7.1）
1. 一档金额
2. 合格集及相关性跳过项
3. 卖出清单
4. 买入清单

### 三、需人工处理
除权除息、待复核、停牌、执行日新增事件和数据缺失
```

合格集为空时写“今日无合格标的，持币”，不得放宽阈值或用盘面事实补位。

### 9.7 唯一交易口径

#### 9.7.0 输入边界

名单只来自 §5，合理价只来自 §6，行情只来自 §8。账户级行为红线与风险阈值另由个人投资体系约束，不在本节重复。

#### 9.7.1 当前参数

| 项 | 当前唯一取值 |
| --- | --- |
| 候选池 | 当日 `worth_attention` |
| 估值 | §6.5 当前生产模型带；`P/V = 收盘 ÷ V` |
| 买入线 | `P/V ≤ 0.9493` |
| 新建仓走势 | `收盘 > MA20 > MA60` |
| 已有持仓加仓走势 | `MA20 > MA60`，不要求收盘高于 MA20 |
| 排序 | `P/V` 升序，资金用尽即停 |
| 相关性 | 与在手及已选标的近 252 日相关性 `≤ 0.70`；超限跳过，最多下扫 40 名 |
| 单次买入 | 当日净资产 `N × 5.0%` |
| 持仓只数上限 | 无 |
| 单票机械上限 | 无 |
| 减持 | `P/V ≥ 2.5548` 且 `收盘 < MA20`，减一档 |
| 换仓 | 资金不足时，候选 `P/V` 至少低 `0.1461`，且被换出持仓 `收盘 < MA20`；卖一档、买一档 |
| 止损 | 由零股建仓时记录成交日 MA60；此后收盘跌破该固定值即整仓清空 |
| 止盈 | 无 |
| 交易单位 | A 股 100 股一手；高价股按 §9.7.3 比例冷却 |
| 执行时点 | T 日收盘信号，T+1 尾盘 14:45-14:55 执行 |

本表是全部交易阈值在文档中的唯一落点。其他章节和其他文档只引用本表，不复写数值。

##### 9.7.1.1 档位基数

`N = 总资产 − 融资负债`，以信号日收盘后的账户净资产计算，每日重算。一档比例取 §9.7.1；按一手向下取整，不为迁就整手而提高档位。

##### 9.7.1.2 生产与回测同步

生产参数落在 `screen_daily_volume_price_signals.py` 的 `SEC97_*` 常量；回测基准落在 `sweep_backtest_configs.py` 的 `BASE`。修改 §9.7.1 时必须同步两处，并运行 `scripts/test_strategy_parameter_sync.py`。

回测新实验一律使用：

```bash
python3 scripts/sweep_backtest_configs.py <配置文件> --out <结果文件>
python3 scripts/sweep_backtest_configs.py --report --out <结果文件>
```

配置文件只写相对 `BASE` 的变化，不手抄完整基准命令。回测宇宙固定读取 `data/processed/pit_attention/panel_moat_bank_v6b.csv`，估值状态固定读取 `data/processed/a_share_daily_states_adopted.csv`。

#### 9.7.2 每日机械顺序

1. 计算全池当日 `P/V`，排除不在名单、流动性不足和 `review_pending` 股票。
2. 形成走势合格集：新建仓与加仓分别使用 §9.7.1 的条件。
3. 按 `P/V` 升序做相关性过滤。
4. 先卖：
   - 收盘跌破固定建仓止损价：整仓清空，且不再走当日其他路径。
   - 触发减持条件：减一档。
   - 已移出 `worth_attention`：每日减一档直至清空，不加走势条件。
   - 想买但资金不足且满足换仓条件：减持最贵的弱势持仓一档。
   - 任何减档后的余仓不足一档时清空。
5. 后买：对过滤后的合格集逐个买一档，按手向下取整，可用资金耗尽即停。

股数以 T 日收盘估算；T+1 按实际成交价调整手数，一档金额不变。

#### 9.7.3 高价股比例冷却

一手金额大于一档时仍成交一手。令 `x = 一手金额 ÷ 一档`，随后跳过 `round(x) − 1` 次该票的合格机会；买入、减持和换仓共用同一计数器。冷却按合格次数，不按自然日。

#### 9.7.4 现有持仓衔接

不做一次性组合重构。在名单内的持仓继续按 §9.7 加减；已出名单的逐档清仓；不因持仓只数多或被动上涨形成高权重而单独卖出。

#### 9.7.5 建仓止损的记录与复位

按 §9.7.1 的止损口径，由零股建仓时把实际成交日的止损基准写入 `entry_stop_price`。加仓不重设，价格上涨不上移，清仓后重新建仓才重设；除权除息按 §11.4 同因子调整。

## 10. 风险过滤与账户防护

### 10.1 买入过滤器

以下任一命中即跳过并顺位补下一名：

1. 不在 `worth_attention`。
2. thesis 已证伪，或存在造假、审计、资金占用与重大治理风险。
3. 20 日平均成交额低于 5,000 万元。
4. `buy_blocked = review_pending`。

第 3、4 项只挡新增买入，不主动触发卖出。

### 10.2 账户级防护

账户回撤梯、担保比例预警、券商授信与强平线按个人投资体系执行。授信额度与融资负债读 §2 的账户快照台账（`credit_line_cny` 列）。每日实际可用资金为：

```text
现金 + max(0, 券商授信额度 − 当前融资负债)
```

该值作为 §8.2 的 `--funds`。负债超过授信额度时不可新增买入，卖出款先偿还超额负债。触及账户级阈值时在当日报告显式提示；未触及时不重复展开。

## 11. 持仓记录与跟踪

### 11.1 持仓侧边界

持仓侧只记录仓位、公告、估值和成交。买卖结论只由 §9.7 产生。

### 11.2 持仓表

`data/processed/a_share_holdings.csv` 固定五列：

```text
security_code, security_name, current_shares, cost_basis, entry_stop_price
```

`cost_basis` 只用于对账；`entry_stop_price` 是 §9.7.5 唯一整仓止损字段。

### 11.3 每日跟踪

```bash
python3 scripts/track_holdings_daily.py --as-of YYYY-MM-DD
```

逐票检查当日公告、披露、重大事项、产业和竞品信息，并显示现档、合理价、空间、`P/V`、止损价与是否命中。行情缺失必须标为“数据缺失”，不得显示为“持有”。

### 11.4 除权除息

除权日必须在策略判定前同时调整带、持仓和止损价：

| 分派 | 带与止损价 | 股数 |
| --- | --- | --- |
| 每股现金红利 `D` | 原值 `− D` | 不变 |
| 每 10 股送转 `k` 股 | 原值 `÷ (1+k/10)` | `× (1+k/10)` |
| 两者并存 | `(原值−D) ÷ (1+k/10)` | `× (1+k/10)` |

`cost_basis` 同价格因子调整。现金分红对带的减项在下一次基本面重建时自然消失；`entry_stop_price` 是历史价格，调整后永久保留。差异化分派按交易所价格口径处理。

检出脚本只提示、不写回；当日报告必须显示“当日持仓除权除息：无/名单”。

### 11.5 成交回写

用户确认成交后：

1. 更新持仓股数与成本；清仓删除该行。
2. 由零股建仓时按 §9.7.5 写入止损价；加仓不改。
3. 决策日志追加 `execution_record`，记录方向、股数、成交价、当日 `P/V` 和对应规则。
4. 次日自动纳入跟踪。

## 12. 改参数与回测验证

参数依据与全部历史读数只查 `docs/Ashare_backtest_log.md`。工作流正文只保存 §9.7.1 当前选择。

### 12.1 验证纪律

新候选按以下顺序验证：

1. 先确认数据、股票池有效期、复权、手续费、整手、融资和执行延迟均与 `BASE` 一致。
2. 预先按预计实盘持有期选收益主窗口，缺省取 5 年；标准 23 个半年起点主报滚动 5 年 CAGR 的配对差中位、正号数和 P10。滚动 3 年只作较短状态诊断，逐年收益只描述单年分布，至今 CAGR 只复核具体长路径；不得看完结果再换主窗口。同时报告回撤、换手与平均仓位。
3. 报逐起点配对差中位和正号起点数，不比较两个独立中位数的差。
4. 参数至少扫描相邻区间，优先选择宽平台，不选择单点峰值；±0.15 个百分点以内视为噪声。
5. 增加互不重叠的持有期或逐年检验；共享终点的多个起点与重叠滚动窗口不视为独立样本。
6. 检查可执行性、幸存者偏差、未来信息和多重比较；绝对收益不当作未来预期。
7. 只有验证通过且用户裁定后，才修改 §9.7.1、生产常量和回测 `BASE`。
8. 实验过程写入回测 log；最终版本变化写入 changelog；当前操作只写回本文件。

历史面板 `effective_from` 与 `effective_to` 均为有效期边界，结束日包含在内。禁止把区间起点当成完整快照，也禁止手工修改面板 CSV；名单变化先改判定源，再运行装配脚本。

换估值口径或换宇宙做 A/B 时，**三条线必须一起重解到同一在册合格面**（`scripts/experimental/align_buy_line.py`），否则比的是两条不同宽度的闸门。现行基准的合格面是下侧 17.960%、上侧 30.465%；各研究臂已解出的线记在 `docs/Ashare_backtest_log.md` §12.83.1。

**当前参数不是三条标准同时占优的峰，而是一条取舍前沿上的一点**：已实测存在滚动 3/5 年更高但逐年中位显著更低的邻居（§12.83.2）。援引本基准时不要说"最优"，要说清是按哪条标准选的。

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
