# OI-228 SEC 取数按申报报表币与准则（2026-09-29，v4.220）

用户 2026-09-29 裁定「采纳并落地」。规则见工作流程 §6.8（三表来源 SEC companyfacts 一段），版本行 v4.220，日志 §12.281。

## 缺陷

`fetch_overseas_statements._sec_series` 对每个标签只取 companyfacts 里排第一的非 pure 单位，`sec_extract`／`PitFacts` 只要 ifrs-full 有 `ProfitLossBeforeTax` 就只读 ifrs-full。于是：

- CRH：20-F 自 FY2020 改美元列报、自 FY2023 改交 us-gaap 10-K，管线停在 FY2019 欧元报表，再直接除以美元股价。
- 美元报表公司的个别外币条目排在美元前面时，整条标签只剩那一条外币值（美股缓存 697 家逐标签扫描）：

| 公司 | 标签 | 外币条目 | 后果 |
| --- | --- | --- | --- |
| SLB | `LongTermDebtNoncurrent` | EUR 5,000m（期末 2020-06-30，10-K 2021-01-27 申报） | 此后年报行有息负债读成 0（实际 97～160 亿美元） |
| PDCO | `ShortTermInvestments` | CAD 45m（10-K 2016-06-29） | 年报行漏计美元短期投资 |
| OMC | `ShortTermBorrowings` | EUR 520m（10-Q 2019-04-16） | 漏计美元短期借款（约 0.1～0.6 亿美元） |
| BMS、PEP、JBL、MPWR、IR、OTIS | 各一两条外币或 AFN 条目 | — | 时点带不变（标签优先级或已被拒绝） |

季报 TTM 路径（`_sec_entries`）按条目数取单位，SLB 等季报点本来正确，只有 BMS、IR 的 1:1 平票可能取到外币，时点带未见影响。观察清单里只有 PDD（人民币）与台积电（新台币）另带美元便利折算，原实现碰巧先取到报表币。

## 改动

- `scripts/fetch_overseas_statements.py`：`purify_currency`（每份申报的报表币 = 该申报货币条目最多的币种，其他币种条目不取）、`sec_frameworks`／`current_framework`（两套准则并读；季报 TTM 用最新申报的准则）、`_period_currency`（逐期报表币 = 报告该期的最新年报的币种）、`sec_extract` 逐期取最新报告该期末总资产的年报所用准则（不用权益：CRH 首份 10-K 的权益变动表把 FY2021 期末权益带出，但该期没有资产负债表，按权益选会取到无债务的 us-gaap 行，投入资本 160 亿对 279 亿），与最新一行币种不同的早年行不连用。
- `scripts/experimental/overseas_pv_forward.py`：`PitFacts` 先清洗，两套准则分别按申报日截断，`current(t)` 给最新申报的准则；`value_worker` 同改。
- `scripts/build_us_daily_states.py`：`PRICE_CCY = "USD"`，最新年报行报表币不是美元的申报点记无法估值（不做汇率折算）。
- `scripts/test_sec_tag_composition.py`：外币零散条目、美元便利折算、币种切换、准则切换四条回归（在旧实现上都失败）。

## 验证

- 既有海外测试（`test_sec_tag_composition`、`test_overseas_supplements`、`test_overseas_valuation_guards`、`test_overseas_report_evidence`、`test_overseas_caliber`）全过。
- 观察清单：`fetch_overseas_statements.py --as-of 2026-09-28`（缓存）输出与入库 `data/interim/overseas_roic_years.csv` 逐字节一致（464 行），清单估值不变。
- 美股历史状态：作业 27315116（`scripts/slurm/oi228_us_states.sbatch`，16 核，2 分 24 秒，MaxRSS 905,774K；首跑 27313393 以权益定准则，只差 CRH），逐申报带 [`us/us_valuation_bands.csv`](us/us_valuation_bands.csv)、覆盖率 [`us/valuation_coverage.csv`](us/valuation_coverage.csv)、对比 [`us/compare.txt`](us/compare.txt)／[`us/compare.json`](us/compare.json)（基线：v4.218 带 `exp_oi226_20260928/us_r2/` 与当时的生产状态）。

| 公司 | 变化申报点 | V 新/旧 | 末日 P/V |
| --- | --- | --- | --- |
| SLB | 12（2023-01-25 起；此前该公司因正常化 NOPAT 非正本就无法估值） | 年报点 −7%～−14%，季报点 +13%～+17%（投入资本历史补回债务）；FY2022 年报点改为股权价值为负，与相邻季报一致 | 2.0463 → 1.8019 |
| CRH | 7（2025-02-26 起，价格缓存始于 2025-02） | 约 3.2 倍（欧元 FY2019 12.88 → 美元 us-gaap 39.39～43.57） | 7.5443 → 2.2241 |
| PDCO | 8（2016-06-29～2018-03-07） | −0.5%～−1.4% | 1.5009 → 1.5086（2018-05-17 末日） |
| OMC | 29（2019-04-16 起） | −0.25%～+0.04% | 1.3130 → 1.3127 |

逐日状态 1,024,486 行／522 家 → 1,024,423 行／522 家（SLB FY2022 年报点被拒，少 63 个交易日）。落地时把候选产物复制为 `data/processed/us_daily_states_{adopted,hold}.csv`（同一代码、同一输入）；v4.218 状态副本 `us/old_states_adopted.csv` 与候选状态不入库。美股回测（BASE_US、H1）未重跑。
