# 谷歌-A（GOOGL）估值档案

> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。

- 质量档：**L1**｜参考分 **84.70**（Q1 90 / Q2 88 / Q3 78 / Q4 76，可信度扣分 0）
- 旗标：erosion_path=AI 原生入口对搜索流量的分流（中概率，2-3年可见）; governance_open_issue=反垄断救济措施未落地; special_advantage_check=搜索默认位分销协议，计入 Q2

## 合理价区间

**247.13 ~ 315.78**

**方法**：PEG×ROE修正：PEG 1.35 × 增速 18.0% → PE 24.3x

**推导**：锚 = 归一化（经常性）EPS 约 $11.3/年（2026Q2 经营利润 $408亿 + 常态其他收入，税率约 17% → 经常性净利约 $340亿/季；剔除股权证券未实现收益）（每股 11.30）；增速 18.0%（从原 25% 下折至 18%：搜索广告个位数增长 + 云双位数增长的混合，AI 对搜索货币化的影响方向未定，不按云的增速外推整体）；ROE 31.8% 落在 25-40%，PEG 取 1.35（介于金山办公 1.25 与同花顺 1.5 之间）；PE = 1.35 × 18 = 24.3x；合理价 = 11.30 × 24.3 = 274.59，× 分层系数 [0.9, 1.15]（L1）= 247.13~315.78。**通用口径为何不成立**：原带直接用 PEG [1.0,1.5] 当带宽（282-424，宽度 1.504），超过 A 股全池 261 条带的最大值 1.278，且 PEG 取值未写 ROE 修正理由。DCF 因资本开支致 FCF 转负而失效（§6.6 步骤2）的判断本档沿用。交叉校验：表观 TTM PE 约 17x 含 $980亿其他收入（主要为股权证券未实现收益），经常性 PE 约 30x——本档用经常性口径，与隐含 PE 24.3x 相比现价略贵

## 参考分理由（§5.7.4）

Q1 90：搜索广告近零边际成本、现金转化极优。Q2 88：搜索默认位与数据飞轮仍是强壁垒，但生成式 AI 首次提供了绕过搜索框的入口，护城河出现真实变数。Q3 78：资本开支激增而回报周期未明，历史上多个非核心项目回报差。Q4 76：创始人双重股权结构、反垄断诉讼缠身，治理透明度中等。

## 跟踪指标

搜索广告收入同比（阈值：连续两季 <5% 即下修 g）；云分部收入增速与经营利润率；资本开支占经营现金流比例；AI 搜索的货币化率；反垄断裁决执行进展

## 复核触发

每季财报；反垄断案裁决与救济措施落地；资本开支指引大幅调整；AI 搜索产品的货币化数据首次披露

---
定档人：模型推导（用户可覆盖）｜复核日：2026-08-03

## ROIC 口径估值（§6.5.2.3 同口径）

更新 2026-08-23（`scripts/build_overseas_roic_bands.py`）。方法：ROIC·增长（§6.5.2.3 同口径）；带 212.65~259.91 USD；审定档 高估。

ROIC·增长（§6.5.2.3 同口径，财年 2021~2025，SEC companyfacts us-gaap）：NOPAT/母公司权益 比率 0.320（ttm_growth）× BPS 33.95 = NOPAT/股 10.857；ROIC0 44.6%；WACC 8.01%（r 8.75% = rf 4.74% + β0.9×ERP 4.46%；rd 2.00%；t 17%；账面权重）；增长 g0=19.5%（来源 trailing：资本腿 10.5%=min(增量ROIC 26.6%,40%)×再投资率 40%，增速腿 19.5%），ROIC_T=min(WACC+档位超额, ROIC0)=14.0%，g_T=3.0%，fade 10 年，终值占比 85%；净负债/股 -5.744（有息负债−超额现金＋少数股东权益）；**V = 236.280 USD/普通股** → **236.28 USD**；带 = V×[0.90,1.10]。标签：capex=PaymentsToAcquirePropertyPlantAndEquipment;cash=CashAndCashEquivalentsAtCarryingValue+CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents;cash_invest=MarketableSecuritiesCurrent;cfo=NetCashProvidedByUsedInOperatingActivities;dep_amort=Depreciation;income_tax=IncomeTaxExpenseBenefit;interest_expense=InterestExpense+InterestExpenseNonoperating;lt_debt_current=LongTermDebtCurrent;lt_d
