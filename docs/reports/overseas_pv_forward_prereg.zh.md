# 海外估值信号预登记前向检验（OI-150）：预登记书与数据前提审计

2026-09-05 写于任何前向读数计算之前。本文件锁定假设、样本、口径、指标与判定；分析脚本以此为准，结果出来前改动须在本文件登记并注明时间。此前只做过数据可得性探测（是否有价、有申报日、有横截面），未计算过任何回报。

## 1. 假设

**H1**：在美股历史时点股票池上，按生产 ROIC 口径（§6.8 与 §6.5.2.3 同式）在每个月末只用当日已申报财报算出的 `P/V`，其分档与其后 3 年／5 年含分红总回报负相关：`P/V` 越低、前向年化越高。

**分档**（与 A 股 `panel_tier_forward.py` 同刻度，买入线与减持线取 A 股在册值以便并列）：`[0,0.8)`、`[0.8,1.0454)`、`[1.0454,1.2)`、`[1.2,1.6)`、`[1.6,2.0)`、`[2.0,2.4257)`、`[2.4257,4)`、`[4,99)`。

**通过判据**（3 年与 5 年各判一次，两者都过才算通过）：①按互不重叠的观测年组（每年 4 月末至次年 3 月末为一组）计算 Spearman(`P/V`, 前向年化)，至少 2/3 的年组为负；②全样本合并后 `[0.8,1.0454)` 档前向年化中位 − `[1.2,1.6)` 档中位 ≥ +3pp。任一不满足即「不支持 H1」。样本剔除超过第 3 节阈值则「不可判」，不改判据凑结论。

**结论用途**：只回答「该估值信号在美股有没有前向信息」，不据此改任何生产规则；若日后据此改规则，美股即转为研究样本、不再是独立检验。港美股与 A 股共享宏观风险，结果按同一日历年组与 A 股并列展示，不做跨市场合并统计。

## 2. 样本（历史时点股票池）

* **市场**：美股（SEC XBRL 申报人，含 IFRS 20-F 外国发行人）。港股无历史股票池来源，只能取现存公司，本轮不作正式样本；若做只标「幸存者样本」。
* **入池规则**：每个日历年 CY 取 SEC XBRL frames 的年度营收横截面（`Revenues`、`SalesRevenueNet`、`SalesRevenueGoodsNet`、`RevenueFromContractWithCustomerExcludingAssessedTax` 四个概念按 CIK 取最大值），剔除 SIC 6000–6799（金融；SIC 缺失者保留并标注），按营收取前 400 名 CIK，作为**次年 4 月末至再次年 3 月末**各月末的观测对象（CY 年报在次年一季度申报完毕，4 月起用避免前视）。
* **观测期**：2010-04 至 2021-03 的月末（腾讯美股日线自 2008 年起；5 年前向最晚到 2026-03，行情末端 2026-08）。
* **退市与幸存者**：frames 有值即入池，不因今日是否存续而剔除。无法取到代码（不在现行 `company_tickers`，`submissions` 亦无 tickers）者记 `no_ticker`；腾讯无历史价者记 `no_price`；两类都计数、按档报告剔除比例。退市公司前向窗口未满时以退市前最后收盘为终值（并购对价含在末价内；破产者按末价，偏乐观，计数）。**阈值**：任一档剔除比例 > 20% 或总体 > 15% 即「不可判」。

## 3. 估值与价格口径

* **时点估值**：对每个观测日 t，把 SEC companyfacts 各概念的事实按 `filed ≤ t` 截断后交 `fetch_overseas_statements.sec_extract`（年报行）与 `sec_current_extract`（最新 10-Q TTM），再交 `build_overseas_roic_bands.value_company` 算 V。全部公司按 L2 档（β 1.0、终值超额 3%），`COMPANY_CFG` 缺省美元口径；rf 取 t 之前最新的美债 10Y（`home.treasury.gov` 年度 CSV，与现行 `rf_usd` 同源）；ERP 取现行常数 0.0446（与 A 股 rf 时变、ERP 常数同法）。V 与 P 都是 t 日股本口径，`P/V` 直接用腾讯未复权收盘 ÷ V。
* **前向总回报**：腾讯美股日线三种模式实测都是未复权（AAPL 2014-06-09 拆股当日 628→92），故拆股按 SEC `StockholdersEquityNoteStockSplitConversionRatio1`（`end` 为拆股日）调整；无该事实但相邻两日收盘比落在 {2,3,4,5,7,10,20 及其倒数} ±3% 且随后一期 SEC 股数同倍变化者亦记为拆股。分红按 SEC `CommonStockDividendsPerShareDeclared` 季度值在该季末收盘再投；两项都缺失视为无拆股无分红并计数。年化 = (TR 终 ÷ TR 起)^(1 ÷ 日历年) − 1。
* **辅助读数**：每档样本数与公司数、对数线性公允点（前向恰等于 r 的 `P/V`，同 `moat_param_lab.loglinear_fair_pv`）、逐年组各档中位。

## 4. 数据前提审计（2026-09-05 实测）

| 前提 | 结果 |
| --- | --- |
| 历史横截面股票池 | SEC frames 可达：`Revenues` CY2015 3,377 家（≥10 亿美元 806 家）、`SalesRevenueNet` 2,085、`SalesRevenueGoodsNet` 1,208；`StockholdersEquity` CY2010Q4I 6,379 家 |
| 财报可得时间 | companyfacts 每条事实带 `filed`（AAPL `NetIncomeLoss` 338 条，2009-07-22～2026-07-31），可按申报日截断 |
| 价格历史 | 腾讯 `fqkline`：美股须带交易所后缀（`usAAPL.OQ`／`usJPM.N`），JPM／AAPL 自 2008、NVDA 自 2010，港股自 2005；退市票（YHOO／TWTR／ATVI／MON／CELG）2015 年有价 |
| 复权 | 腾讯美股 `qfq`／`hfq` 与未复权逐日相同，不可用；拆股与分红改由 SEC 事实推 |
| 无风险利率历史 | `home.treasury.gov` 年度 CSV 可达（2010 年 253 行，10Y 列） |
| 退市公司代码与行业 | `submissions` 对已注销公司 `tickers`／`sic` 为空（Altaba），代码只能靠现行 `company_tickers` 与曾用名；缺口按第 2 节计数 |
| 其它源 | FRED 超时、东财 `push2his` 本节点不可达，都不依赖 |

**缺口**：①2019 年前退市且现行代码表无记录的公司取不到代码，属幸存者偏差来源（方向：抬高各档回报，对档间差的影响方向不定），按阈值处置；②ERP 取常数；③港股无历史池。

## 5. 执行计划

`scripts/experimental/overseas_pv_forward.py` 子命令：`universe`（frames → 逐年前 400 CIK 与 SIC）、`facts`（companyfacts 与 submissions 落 `data/experiments/exp_oi150_overseas_forward/raw/`，不入库）、`prices`（腾讯日线落同目录）、`value`（逐公司逐月末 PIT `P/V`）、`report`（第 1 节判据）。作业 `scripts/slurm/oi150_overseas_forward.sbatch`；取数只在计算节点跑。产物与报告落 `data/experiments/exp_oi150_overseas_forward/`，结论写回测日志一节并在 OI-150 登记项处置。
