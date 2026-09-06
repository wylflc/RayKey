# 美股移植评估与执行计划（OI-150 后续：历史标普成分股 ＋ 现行估值与交易规则）

2026-09-06 写于任何美股回测读数之前。目标：把 A 股现行策略（§6.5.2.3 ROIC 口径估值 ＋ §9.3 交易规则）原样搬到美股，
股票池不用 LLM 护城河筛选，改用**历史时点的标普 500 成分股**；只回答「同一套估值与操作规则在美股上读数如何」。

## 1. 结论摘要

| 项 | 评估 |
| --- | --- |
| 总工作量 | 约 **8 个工作日**（六个阶段，见 §5），其中新代码约 4 个脚本、引擎改一处配置层 |
| 计算量 | 全部作业合计 **< 3 小时**（rome `-n 16`）；SEC 取数约 20 分钟、取价 ≤ 1 小时、建逐日状态约 10 分钟、扫描 9 起点 × 2~3 臂 ≤ 2 小时 |
| 数据成本 | **0~30 美元**：SEC、FRED、标普历史成分免费；退市价格需付费一个月（Tiingo Power 30 美元/月 或 EODHD 19.99 欧元/月） |
| 可复用 | OI-150 已有：SEC 时点股票池、653 家 companyfacts 缓存（1.9 GB）、按申报日截断的 `PitFacts`、已统一到 A 股口径的 `value_company`（v4.139/v4.140） |
| 主要不确定 | ① 估值引擎在美股样本上只覆盖 55%~67%（§3.2）；② XBRL 自 2009 年起，2012 年前多数公司不足 3 个财年，起点集比 A 股少 5 个；③ 退市代码映射缺口约 7%（§3.3） |

## 2. 现状盘点（可复用部分）

* `scripts/experimental/overseas_pv_forward.py`（OI-150）：`universe`（SEC frames 逐年营收前 400，剔除 SIC 6000–6799）、`facts`（companyfacts 下载）、`PitFacts.at(t)`（按 `filed ≤ t` 截断）、`value_worker`（→ `fetch_overseas_statements.sec_extract` / `sec_current_extract` → `build_overseas_roic_bands.value_company`）。时点估值链已通，**只差把「逐月末」改成「逐次申报」并展开成逐日状态**。
* 缓存：`data/experiments/exp_oi150_overseas_forward/raw/sec/` 653 家 companyfacts；标普池约 850 家，与之重叠部分不必重取。
* `backtest_valuation_strategy.py` 读逐日状态文件只用五列：`security_code`、`date`、`close`、`intrinsic_value`、`valuation_ratio`（其余列可空）；宇宙面板只用 `security_code`、`effective_from`、`effective_to`。

## 3. 实测（2026-09-06）

### 3.1 数据源可达性（登录节点与计算节点 tcn420 各测一遍，结果一致）

| 源 | 用途 | 可达 | 费用 | 备注 |
| --- | --- | --- | --- | --- |
| SEC `data.sec.gov` companyfacts / frames / submissions | 三大报表（PIT）、股票池、CIK↔代码 | 200 | 免费 | 含退市公司；每条事实带 `filed`；XBRL 自 2009 年（10-K 内含 2~3 年可比数） |
| GitHub `fja05680/sp500` | 标普 500 历史成分（1996 起每日快照 2,718 行；`sp500_ticker_start_end.csv` 1,259 个区间） | 200 | 免费 | 2011 年后与维基「Selected changes」核对；2001 年前不完整，本计划不用 |
| Tiingo EOD | 未复权收盘＋`divCash`／`splitFactor`；含退市 | 403（需免费 token） | 免费档 50 请求/时、1,000/日、500 代码/月；Power 30 美元/月 | 退市样本 YHOO／TWTR／ATVI／CELG／MON 均有 |
| EODHD | 同上，含退市与拆分分红 | 401（需 key） | 19.99 欧元/月，10 万次/日 | 备选 |
| Yahoo `v8/finance/chart` | 收盘、`adjclose`、拆股与分红事件 | 200 | 免费 | **退市代码全部 404**（YHOO／TWTR／ATVI／CELG／MON），不能做历史池 |
| Sharadar（Nasdaq Data Link） | SEP 价格、ACTIONS、SP500 成分、TICKERS（含 CIK） | 403（需 key） | 价格需登录查看，未核实 | 一站式最省事；用户若已有订阅则优先 |
| FRED `fredgraph.csv?id=DGS10` | 美债 10Y 日序列（rf） | 200 | 免费 | 替代 `home.treasury.gov`（登录节点超时） |
| 腾讯 `fqkline` | — | — | — | 限流约 250 请求/33 分钟，弃用 |

### 3.2 估值引擎覆盖率（OI-150 缓存的 653 家中随机 60 家，四个时点，`value_company` L2、rf 2%、ERP 4.46%）

| 时点 | ok | rejected | no_annual |
| --- | ---: | ---: | ---: |
| 2012-12-31 | 36 | 16 | 8 |
| 2016-12-31 | 36 | 19 | 5 |
| 2020-12-31 | 33 | 27 | 0 |
| 2024-12-31 | 40 | 20 | 0 |

拒绝原因（240 个公司·时点）：股数不可得（无稀释加权/期末股数标签）24 个（10%，**映射缺口，可修**）；结构断点后财年不足 3 年 17 个（7%，口径固有：20% 账面跳变重切窗口）；母公司权益非正 13 个（5%，回购吃光账面，A 股口径判无法估值）；NOPAT ≤ 0、净负债超企业价值各 1~2 个。
60 家 × 4 时点估值耗时 10 秒，单核约 0.04 秒/次。

### 3.3 标普池与价格源的代码映射（`sp500_ticker_start_end.csv` ∩ Tiingo `supported_tickers`）

* 2011 年后有效的成员区间 847 个、代码 829 个，其中 342 个已出指数。
* 61 个代码（7.4%）在 Tiingo 列表无同名序列：多数是改名（FB→META、ANTM→ELV、UTX→RTX、ABC→COR、BLL→BALL、FLT→CPAY、RE→EG、PKI→RVTY）或已被收购退市（SIVB、FRC、BBBY、JCP、CTL）；另有 BK、EQR、MMC 等现役代码也不在列表里，说明该列表文件本身有缺漏，**定论要用 token 实测**。
* 6 个代码序列末日早于出指数日，差 1~3 个交易日，可忽略。
* 出指数即卖出（§9.3.2「已移出名单」路径），故退市价格只需覆盖到出指数日。

### 3.4 回测引擎里的 A 股特有项（移植清单）

| 项 | 现状 | 美股取值 |
| --- | --- | --- |
| 路径常量 | `OHLCV_DIR`、`ACTIONS`、`DELISTED_ROSTER`、`RATES`、`BENCHMARK=INDEX_000300`、`load_names`/`load_tiers` 读 A 股分层表 | 加 `--market us` 配置层：`data/raw/ohlcv_us/`、`us_corporate_actions.csv`、`us_delisted_roster.csv`、`cost_of_equity_inputs_us.csv`、`INDEX_SPX.csv` |
| 代码格式 | `zfill(6)` 三处（引擎两处、`pv_ratio.py` 一处） | 按市场跳过补零 |
| 年交易日 | `TRADING_DAYS = 244`（Sharpe、年化波动） | 252 |
| 交易单位 | `--lot-size 100` | 1 |
| 费税 | `--fee-preset user`（佣金万一、最低 5 元、印花税 0.05%、过户费） | 佣金 0、印花税 0；只留 `--slippage-bp` |
| 股息税 | 差别化持有期税率（FIFO） | 新增固定预提率模式（参数，缺省 0）；美股无持有期税率 |
| 融资 | 授信 66.6%、强平 130%、利率 3.5% | 比例沿用；利率作参数（美国券商约 5%~6%，待用户给值） |
| 公司行动 | 现金、送转、配股 | 现金分红→`cash_per_share`；拆股 k:1→`share_ratio = k−1`（反向拆股为负，需测）；配股无；**分拆（spin-off）不可表示**，按分拆日子公司市值折算成现金红利并计数 |
| 退市名册 | 末个交易日 | 取价格源序列末日与出指数日的较早者 |
| 执行时点 | T+1 尾盘 14:45–14:55 | T+1 收盘（引擎 `--exec-price` 缺省即收盘） |
| 基准 | 沪深 300 | 标普 500 全收益（只进 summary，不进判定） |

## 4. 需用户裁定的范围项

**裁定（2026-09-06）**：股票池取 A（标普 500 历史成分）；金融股第一期剔除；其余按推荐。固定取值见预登记书 [us_sp500_backtest_prereg.zh.md](us_sp500_backtest_prereg.zh.md) §0。

1. **股票池**：A) 标普 500 历史成分（推荐，约 850 家，1996 起）；B) 标普 100 历史成分（更严，无免费历史成分源，需付费）；C) SEC 营收前 400（OI-150 已建，无幸存者与代码映射问题，但不是指数）。
2. **金融股**：第一期按 OI-150 剔除 SIC 6000–6799（标普约 65 家）；第二期再移植银行/保险股利折现（§6.7 第 3 步，需 `CommonStockDividendsPerShareDeclared` 按财年归属）。
3. **负权益公司**（HD、MCD、BA 一类）：按 A 股口径判无法估值、不进合格集，不另设口径。
4. **两条线**：按用户指令主臂沿用 **1.0454 / 0.15**；§12 要求换宇宙须用 `align_buy_line.py` 对齐到同一合格面，作第二臂并列报，不作主读数。
5. **交易参数**：初始资本以美元计（建议 50 万美元，档位比例不变）；融资利率；股息预提率（0 / 15% / 30%）。
6. **起点集**：路径 ≥10 年的半年档起点自 2012-05-01 起（XBRL 三年史成立后），共 9 个；2009-11／2011-11 两个长跑锚点在美股不可用，改报 2012-05。

## 5. 执行计划

| 阶段 | 内容 | 产物 | 工时 |
| --- | --- | --- | --- |
| P0 预登记与裁定 | 写预登记书（假设、样本、口径、判据、剔除阈值 15%/20% 沿用 OI-150）；§4 六项裁定；申请数据 token | `docs/reports/us_sp500_backtest_prereg.zh.md` | 0.5 d |
| P1 数据层 | ① 标普历史成分 → 面板（`effective_from`/`effective_to`，与 v6b 同格式）＋ 代码→CIK 解析（`company_tickers` ＋ `submissions` 曾用名 ＋ OI-150 的申报文件封面代码反查），未解析者计数；② 取价器：Tiingo/EODHD → `data/raw/ohlcv_us/<代码>.csv`（未复权，与 A 股同六列）＋ `us_corporate_actions.csv`（A 股事件表同列）＋ 退市名册；③ FRED DGS10 → `cost_of_equity_inputs_us.csv`（同列）；④ 复用 `overseas_pv_forward.py facts` 补取标普池 CIK 的 companyfacts | `scripts/build_us_index_panel.py`、`scripts/fetch_us_ohlcv_history.py`、`scripts/slurm/us_data.sbatch` | 2.5 d |
| P2 估值逐日状态 | `build_us_daily_states.py`：逐 CIK 按每次 10-K/10-Q `filed` 日重算 V（PIT），`band_available_at = filed`、生效日取前一交易日（与 A 股 `--state-effective prev_trading_day` 同）；展开逐日：拆股因子折 V、公告后现金分红按 §11.4 归一化；写候选侧文件（五列必填）；先修股数标签缺口（§3.2）；可选：把 `--ttm-trust` 规则移植进 `value_company` 出 B2/持仓侧，否则持仓侧＝候选侧并登记为成文差异；覆盖率审计表（逐年 ok/拒绝原因） | `data/processed/us_daily_states_adopted.csv`（约 250 万行）、`us_daily_states_hold.csv`、覆盖率表 | 2 d |
| P3 引擎配置层 | §3.4 清单落地为 `--market us`；固定预提股息税模式；**回归：A 股 `BASE` 单起点逐位不变**（`test_strategy_parameter_sync.py` 加一条） | 引擎改动 + 测试 | 1.5 d |
| P4 扫描 | `sweep_backtest_configs.py` 加 `BASE_US` 与起点集；臂：主臂（1.0454/0.15）、对齐臂、`--exclude-codes` 剔除集 A；滑点 0/10/20/30bp | `data/experiments/exp_us_sp500_port/`、`scripts/slurm/us_sp500_sweep.sbatch` | 1 d |
| P5 报告 | 决策读数三段版面（§12.1 第 2 款）、覆盖率与剔除比例、与 A 股在册读数并列（不合并统计）；回测日志一节；OI-150 处置 | 回测日志节、OI 登记 | 0.5 d |

顺序：P0 → P1（①②③④ 可并行）→ P2 → P3（可与 P2 并行）→ P4 → P5。

## 6. 风险与边界

* **幸存者**：财报侧无（SEC 含退市）；价格侧取决于付费源对退市代码的覆盖，按预登记阈值处置（总体 > 15% 即不可判）。
* **前视**：估值只用 `filed ≤ t` 的事实；成分股变动按公告生效日；标普历史成分文件的日期精度为日。
* **口径差异（登记，不改）**：季报净负债取 10-Q 资产负债表、`x` 无 −25% BPS 下限（沿用 v4.140 头注）；分拆按现金折算；持仓侧若未移植 B2 则与候选侧相同。
* **样本含义**：标普成分是市值与盈利筛选，不等价于护城河筛选；美股与 A 股共享宏观风险，结果只并列展示、不跨市场合并；据此改规则后美股转为研究样本（与 OI-150 预登记同）。
* **历史长度**：XBRL 三年史自 2012 年成立，标准起点 9 个而非 14 个；付费基本面（Sharadar SF1 自 1998 年）可向前延伸，但提取口径与 SEC 原始概念不同，属第二期。
