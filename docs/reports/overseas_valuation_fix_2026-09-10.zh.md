# 海外估值缺陷修复与全清单更新（2026-09-10）

**两项缺陷已修复，29 家海外公司的清单、公司档案和总览已同步。** 22 家可计算 ROIC 估值，2 家金融公司依工作流保留已核验 PB 带，5 家继续无法估值。与修复前相比，模型价值仅迪士尼和 Adobe 变化；前者来自利息输入纠错，后者来自本次纳入的新季报。质量档、评分、名单分类及估值参数表均未改变。

海外利息缺陷原登记为 OI-175，与此前少数股权问题重号，现改为 **OI-177**；薄权益遗漏仍为 **OI-176**。两项在工作流 v4.180 结案。[最初的迪士尼核验](disney_pv_pe_audit_2026-09-10.zh.md)保留修复前读数及当时编号，不能作为当前估值。

## 当前结果

金额均为各自交易币种；下表两家公司均为 USD。现价是 2026-09-10 公开行情快照，不作为当日收盘价声明。合理估值取已落库估值带的中点，完整清单见[总览海外附表](../000_a_share_core_valuation_pool.md#附海外关注清单非a股观察口径)。

| 公司 | 更新前 V | 更新后 V | 当前合理价区间 | 现价 | 当前 P/V | 变化原因 |
| --- | ---: | ---: | --- | ---: | ---: | --- |
| 迪士尼 DIS | 26.46 | 37.83 | 34.05～41.61 | 105.82 | 2.797 | 年度及 TTM 利息费用符号纠错 |
| Adobe ADBE | 214.79 | 225.33 | 202.80～247.86 | 248.83 | 1.104 | 纳入 FY2026Q3 官方业绩三表 |

其余 20 家可计算 ROIC 的公司，未舍入模型价值与修复前一致。伯克希尔、中信股份保留金融企业 PB 估值带，中值分别为 417.10 USD、18.00 HKD。美团和英特尔因最新 NOPAT 非正继续拒绝；三星电子、SK 海力士、SpaceX 因现有三表来源不足继续无法估值。上述 5 家的合理价及 P/V 均为空，没有恢复历史估值。

29 家均取得本次行情。结构化前后对照、完整模型输出及验证结果分别见 [comparison.csv](../../data/interim/overseas_valuation_fix_20260910/comparison.csv)、[model_results.json](../../data/interim/overseas_valuation_fix_20260910/model_results.json)、[verification.json](../../data/interim/overseas_valuation_fix_20260910/verification.json)。阅读版使用行情原始精度，而价格落库保留两位小数；P/V 核对允许这一舍入差异。

## 修复内容

**OI-177：单期费用语义统一后再滚动。** `fetch_overseas_statements.py` 仅将 SEC 纯利息费用字段转为费用正值，年度取数和 TTM 的年报、本期累计、同期累计均在组合前处理。税收收益、净利润等字段保留原始符号。迪士尼 TTM 利息因此从错误的 −1.829 billion 修正为 `1.812 + 1.379 − 1.396 = 1.795 billion`；不是对最终 TTM 取绝对值。

迪士尼 FY2023～FY2025 及当前 TTM 共 4 行利息、EBIT、NOPAT 修正。当前 TTM EBIT 为 14.545 billion，NOPAT 为 10.5363 billion；未舍入 V 为 37.828725。保持最初审计价 104.81 不变时，P/V 从 3.9610 降为 2.7706；本次 2.797 还包含行情更新。历史归一化、峰值守卫及零增长路径均保留，没有采用原报告关闭峰值守卫的诊断估值。

**OI-176：两条估值路径共用固定扣减口径。** `build_overseas_roic_bands.py` 复用 `minority_claims.equity_bridge`，在零增长及增长路径的股权桥后执行[工作流 §6.5.1](../000_Ashare_workflow.md)薄权益守卫。随企业价值变化的少数份额不算固定扣减；少数股东账面下界生效时计入固定部分。拒绝时不返回合理价，并沿现有写回路径清空 CSV 估值带、公司档案和总览估值单元格。

用迪士尼修复前真实输入通过新守卫复算，固定扣减／企业价值为 51.8394%，结果正确拒绝。修正利息后变为 42.9519%，不再触发。本次所有 22 家可估值公司均通过守卫；最高为京东的 47.2908%。因此，守卫已补齐，但本批没有新增无法估值公司。

## 财报与数据边界

本次从已成功缓存的 SEC／港股原始三表及官方维护行重新提取，补取缺失的公开股息辅助数据；**未对全部远端三表做强制重新下载**。重建前后均为 444 行，没有丢失年度覆盖。除迪士尼 4 行外，已有提取器的字段候选补出了特斯拉早期 4 年股数、康宁 2007 年权益及股数、台积电 2015 年权益，共 6 条历史行；这些早期变化未改变当前估值。另有 91 条共同记录的标签元数据变化。逐字段差异及 Adobe 替换行见 [statement_changes.json](../../data/interim/overseas_valuation_fix_20260910/statement_changes.json)，文件与原始缓存哈希见 [manifest.json](../../data/interim/overseas_valuation_fix_20260910/manifest.json)。

Adobe 在 9 月 10 日披露截至 8 月 28 日的 FY2026Q3 业绩，附未经审计的利润表、资产负债表和现金流量表，正式 10-Q 尚待提交。因此依 §6.8 官方维护行机制推进财报期及证据日，替换原 FY2026Q2 TTM。[Adobe 官方业绩公告](https://www.adobe.com/cc-shared/assets/investor-relations/pdfs/01906202/au56y4ter.pdf)

利润表按 FY2025＋本年前九月−上年前九月构造 TTM；公告现金流量表展示单季，故按原 Q2 TTM＋本次 Q3−上年 Q3 滚动。结果为收入 25.970 billion、税前利润 9.281 billion、利息费用 0.260 billion、净利润 7.284 billion、经营现金流 10.806 billion，最新季度稀释股数 395 million。逐项原始数字和计算基数见 [adobe_q3_source.json](../../data/interim/overseas_valuation_fix_20260910/adobe_q3_source.json)。公告未披露当前 TTM 综合收益，该字段留空；当前模型归一化使用历史年报综合收益，不受此空值影响。公司清单已注明正式 10-Q 披露后核对并替换维护行。

阿里巴巴清单的 9 月 4 日为过期预期日期；官方最新季度业绩仍是 8 月 20 日披露的六月季度。本次清除该错误预期日期并保留官网核对来源，没有把核对日写成财报证据日。[阿里巴巴官方披露列表](https://www.alibabagroup.com/en-US/ir-news-filings)、[季度业绩公告](https://www.alibabagroup.com/en-US/document-2026456290057781248)

## 验证与复现

8 项新增回归通过，覆盖三期费用符号的全部 8 种组合、税收收益符号保留、IFRS 费用字段、两条路径的薄权益临界点上下及等号、少数权益固定／比例部分、非正权益拒绝，以及拒绝在 CSV 和两个阅读入口的传播。已有 12 项海外财报证据测试通过。全清单检查确认 29 份档案和 29 行总览与结构化输入一致，5 家无法估值行没有有效价格带；A 股核心池 CSV 和海外估值参数表的哈希与修复前一致。

```bash
python3 scripts/test_overseas_valuation_guards.py
python3 scripts/test_overseas_report_evidence.py
python3 data/interim/overseas_valuation_fix_20260910/verify.py
python3 scripts/fetch_overseas_earnings_calendar.py --as-of 2026-09-10 --check-only
python3 scripts/audit_repository_docs.py
```

上述验证脚本针对本次冻结基线 `c25e3e77` 和本次生产快照；未来财报或行情变化后应另建批次，不覆盖本报告结论。生产更新命令为 `fetch_overseas_statements.py --as-of 2026-09-10`、`build_overseas_roic_bands.py --as-of 2026-09-10 --quotes fetch`、`build_a_share_core_valuation_pool.py --md-only --quotes fetch --signal-date 2026-09-10`。本次先验证临时三表文件完整再替换生产文件；纳入 Adobe 新财报后再次构建估值与总览。财报日历自检无逾期，决策日志追加缺陷关闭和 Adobe 同日改判记录。
