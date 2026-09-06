# 美股标普 500 历史成分股组合回测（OI-159）：预登记书

2026-09-06 写于任何美股回测读数之前。本文件锁定假设、样本、口径、参数、指标与判定；脚本以此为准，结果出来前的改动须在本文件登记并注明时间。
工作量评估与阶段计划见 [us_sp500_strategy_port_plan.zh.md](us_sp500_strategy_port_plan.zh.md)。与 OI-150 的关系：OI-150 预登记书是分档前向检验（第一步），本件是它预告的「完整组合回测」；数据层共用，OI-150 的分档表作本件副产物。

## 0. 裁定记录（用户 2026-09-06）

| 项 | 裁定 |
| --- | --- |
| 股票池 | 标普 500 历史成分 |
| 金融股 | 第一期剔除 SIC 6000–6799（含 REIT 6798） |
| 负权益公司 | 按 A 股口径判无法估值，不另设口径 |
| 两条线 | 主臂沿用 1.0454 / 0.15；对齐臂并列报、不作主读数 |
| 初始资本 | 500,000 美元 |
| 融资 | 授信 66.6%、强平 130%（与 A 股同）；利率 5.0%（IBKR Pro 2026 年 USD 首档 5.12%、10 万~100 万美元档约 4.6% 的折中；描述臂 3.5%） |
| 股息税 | 现金红利固定预提 15%（假设荷兰税务居民并已提交 W-8BEN；描述臂 0%） |
| 起点集 | 2012-05-01 起半年档、路径 ≥ 10 年，共 9 个；长跑锚点 2012-05-01 |

## 1. 假设

**H1**：在美股历史标普 500 非金融成分上，按 A 股现行估值口径与 §9.3 交易规则运行，滚动 5 年 CAGR 对标普 500 全收益指数同窗口 CAGR 的逐起点配对差中位在至少 6/9 个起点为正，且 9 个起点的配对差中位 ≥ +3pp。任一不满足即「不支持 H1」；样本剔除超过第 2 节阈值即「不可判」，不改判据凑结论。

**结论用途**：只回答「同一套规则在美股是否有效」，不据此改任何生产规则。港美股与 A 股共享宏观风险，读数与 A 股在册读数并列展示、不合并统计；若日后据美股结果改规则，美股即转为研究样本。

## 2. 样本

* **成分来源**：GitHub `fja05680/sp500` 的 `S&P 500 Historical Components & Changes (Updated).csv`（1996 起每日快照）。下载件存 `data/raw/us/sp500_history/`（不入库），记录下载日与 SHA-256。2011-01-01 起与维基 List of S&P 500 companies 的 Selected changes 逐条核对，差异登记在面板同目录的 `panel_sp500_us_audit.csv`。
* **成员区间**：同一代码连续出现的快照日段为一个区间；`effective_from` = 首个快照日，`effective_to` = 消失前最后一个快照日。面板 `data/processed/pit_attention/panel_sp500_us.csv`，与 `panel_moat_bank_v6b.csv` 同列。面板自 2009-01-01 起（起点前热身），观测窗 2012-05-01 至数据末端。
* **代码 → CIK**：① SEC `company_tickers.json` / `company_tickers_exchange.json`；② `submissions` 的 `tickers` 与 `formerNames`；③ OI-150 的申报文件封面代码反查（CIK 侧取全部 XBRL 申报人）；④ 手工映射 `data/reference/us_ticker_cik_overrides.csv`，每行注明依据。未解析记 `no_cik`。
* **金融剔除**：按 `submissions` 的 `sic` 剔除 6000–6799；SIC 缺失者保留并标注。金融剔除单独计数，不算样本损失。
* **价格与公司行动**：Tiingo 日线（token 只从环境变量 `TIINGO_TOKEN` 或 `~/.config/raykey/tiingo_token` 读取，不入库）。未复权收盘 → `data/raw/ohlcv_us/<代码>.csv`（`date,open,close,high,low,volume` 六列，与 A 股同）；`divCash`／`splitFactor` → `data/raw/corporate_actions/us_corporate_actions.csv`（A 股事件表同列：现金红利 → `cash_per_share`，拆股 k:1 → `share_ratio = k − 1`，反向拆股为负比例）；退市名册 `data/raw/us_delisted_roster.csv`，末个交易日 = min(价格序列末日, 出指数日)。无价记 `no_price`。改名公司按 Tiingo 现行代码取全史，原代码的成员区间沿用。
* **退市与出指数**：出指数走 §9.3.2「已移出名单」路径逐档清仓；价格序列在出指数前结束者按退市名册在末个交易日以末价清仓（并购对价含在末价内；破产者按末价，偏乐观，计数）。
* **分拆（spin-off）**：按分拆日子公司首日收盘 × 分配比例折算为现金红利记入事件表，逐笔计数。
* **阈值**：按成员·日计，`no_cik + no_price` 总体 > 15% 或任一年 > 20% 即「不可判」。
* **幸存者与前视**：财报侧 SEC companyfacts 含退市公司；估值只用 `filed ≤ t` 的事实；成分变动按快照日生效。

## 3. 估值口径

* 与 §6.8 / §6.5.2.3 同式，实现为 `build_overseas_roic_bands.value_company`：全部 L2（β 1.0，对应 A 股 `--uniform-tier L2`），r = rf + 1.0 × ERP，rf 取 FRED `DGS10` 在 t 之前的最新值，ERP 常数 0.0446。
* **时点**：每次 10-K／10-Q（20-F／40-F 同）`filed` 日 F 重算 V；`band_available_at = F`，逐日状态里带的生效日 = F 之前最后一个交易日（与 A 股 `--state-effective prev_trading_day` 同）。6-K 申报、不在 companyfacts 的公司判无法估值。
* **归一化**：报告期末至当日的拆股按比例折 V；生效后的现金分红按 §11.4 `V − D`，到下一份报告接管为止。
* **持仓侧**：第一期 = 候选侧（`--ttm-trust` 规则未移植，作成文差异登记）。若在跑数前移植 B2，在此登记时间并改为逐 (代码, 日期) 取两侧较高 V。
* **无法估值**（负权益、NOPAT ≤ 0、结构断点后不足 3 年、股数不可得等）无 `P/V`、不进合格集；逐年报告各原因占比（描述项）。股数标签缺口先修（P2），修后重估覆盖率并在此登记。
* 产物：`data/processed/us_daily_states_adopted.csv`／`us_daily_states_hold.csv`，`security_code`、`date`、`close`、`intrinsic_value`、`valuation_ratio` 五列必填。

## 4. 交易口径

§9.3.1 与 §9.3.2 逐条同式，只改下表市场项：

| 项 | 取值 |
| --- | --- |
| 交易单位 | 1 股（`--lot-size 1`），无比例冷却 |
| 费税 | 佣金 0、印花税 0、过户费 0；滑点 0／10／20／30bp 四档（§12.1 第 7 款） |
| 股息税 | 现金红利按 15% 固定预提，卖出时不结算、不退（引擎新增固定预提模式） |
| 融资 | 授信 = 净资产 × 66.6%、强平线 130%、年利率 5.0%；资金顺序按 §10.2 |
| 初始资本 | 500,000 美元 |
| 执行 | T 日收盘信号、T+1 收盘成交；T+1 无价跳过；同日买卖对冲；同日一档 |
| 均线 | 前复权口径 MA20／MA60，引擎按事件表映射到末日口径（与 A 股同） |
| 基准 | 标普 500 全收益（Yahoo `^SP500TR` → `data/raw/ohlcv_us/INDEX_SP500TR.csv`），只进 summary |
| 无风险利率 | FRED `DGS10` → `data/reference/cost_of_equity_inputs_us.csv`（列同 A 股） |
| 年交易日 | 252 |
| 买入线／换仓边际 | 主臂 1.0454／0.15；对齐臂按 `align_buy_line.py` 把买入线对齐到 A 股在册合格面（候选侧下侧比例 17.771%），换仓边际同倍缩放 |

## 5. 指标、起点集与臂

* 计量口径 m2。标准起点集 = 2012-05-01、2012-11-01、…、2016-05-01 共 9 个；长跑锚点 2012-05-01（单起点，只报水平）。
* 每臂报 §12.1 第 2 款标准指标集（全样本与去赢家各一份）、跨起点尾部、集中度表。剔除集 A = `BASE_US` 臂 2012-05-01 起点按相对贡献前五；不做 U。
* **H1 读数**：逐起点「滚动 5 年 CAGR 中位 − `^SP500TR` 同窗口 CAGR 中位」的配对差；报 9 个起点的配对差中位与正号起点数。
* 臂（共 7 条 × 9 起点）：`BASE_US`；`ALIGNED_US`；`BASE_US` 滑点 10／20／30bp；`BASE_US` 利率 3.5%；`BASE_US` 预提 0%。后四条只描述。
* 辅助（不进判定）：`panel_tier_forward.py` 在美股候选侧状态上的 `P/V` 分档前向回报（OI-150 的分档表）；覆盖率表；与 A 股在册读数并列表。

## 6. 执行

阶段与产物按计划文档 §5。作业 `scripts/slurm/us_sp500_data.sbatch`、`us_sp500_states.sbatch`、`us_sp500_sweep.sbatch`；取数只在计算节点跑。产物落 `data/experiments/exp_us_sp500_port/`（`raw/` 不入库）。结论写回测日志一节，并在 OI-159 处置。

## 7. 数据前提审计

2026-09-06 实测见计划文档 §3：SEC、FRED、GitHub 成分文件在登录节点与计算节点均可达；Tiingo 需 token；Yahoo 退市代码全缺，只用于指数序列；估值引擎在 OI-150 样本上覆盖 55%~67%，股数标签缺口 10% 待修。
