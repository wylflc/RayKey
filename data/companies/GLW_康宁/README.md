# 康宁（GLW）估值档案

> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。

- 质量档：**L2**｜参考分 **67.80**（Q1 66 / Q2 70 / Q3 64 / Q4 70，可信度扣分 0）
- 旗标：erosion_path=显示面板业务长期价格通缩（高概率，已发生）; special_advantage_check=特种玻璃配方与工艺，计入 Q2

## 合理价区间

**42.07 ~ 51.98**

**方法**：PEG×ROE修正：PEG 1.0 × 增速 15.0% → PE 15.0x

**推导**：锚 = FY2026E 核心 EPS 约 $3.30（核心口径；GAAP EPS $2.17 含汇率对冲与减值噪音，PE(TTM) 57.8x 失真）（每股 3.30）；增速 15.0%（Springboard 计划指引 2026Q4-2030Q4 销售 CAGR 19%，下折至 15% 以反映显示面板业务的周期性与光通信订单的集中度风险）；ROE 13.5% <15%，资本效率不支持成长溢价，PEG 取判例下限 1.0；PE = 1.0 × 15 = 15.0x；合理价 = 3.30 × 15.0 = 49.50，× 分层系数 [0.85, 1.05]（L2）= 42.07~51.98。**通用口径为何不成立**：原带「2028E 核心 EPS $5.00 × 合理PE 23x」——锚含两年外推、倍数 23x 无推导，两处叠加；本档改回当年度锚，把外推交给 g 一个参数承担。⚠本档与原带差异最大（原带 92-115，本档显著更低），原因就是锚从 2028E $5.00 换回 2026E $3.30。若 Springboard 的销售 CAGR 19% 如期兑现，2028 年的带会自然抬上去——但那要等它兑现，不是现在就把它算进锚

## 参考分理由（§5.7.4）

Q1 66：重资产制造、周期性明显，但特种材料的配方与工艺积累带来定价权。Q2 70：玻璃基板与光纤的材料科学壁垒真实存在，客户认证周期长。Q3 64：多年资本开支回报参差，Springboard 之前的增长长期低于承诺。Q4 70：披露规范，核心口径与 GAAP 差异解释充分。

## 跟踪指标

光通信分部营收同比（阈值：连续两季环比下滑即下修 g）；显示面板价格与稼动率；核心 EPS 与 GAAP EPS 的差额（阈值：差额 >50% 需说明）；Springboard 目标兑现进度；ROE

## 复核触发

每季财报；Springboard 阶段目标兑现或下修；AI 数据中心光连接订单变化；显示面板周期拐点

---
定档人：模型推导（用户可覆盖）｜复核日：2026-08-03

## ROIC 口径估值（§6.5.2.3 同口径）

更新 2026-08-23（`scripts/build_overseas_roic_bands.py`）。方法：ROIC·增长（§6.5.2.3 同口径）；带 18.96~23.17 USD；审定档 高估。

ROIC·增长（§6.5.2.3 同口径，财年 2021~2025，SEC companyfacts us-gaap）：NOPAT/母公司权益 比率 0.134（cyclical_median，周期守卫命中）× BPS 13.56 = NOPAT/股 1.819；ROIC0 9.1%；WACC 6.95%（r 9.20% = rf 4.74% + β1.0×ERP 4.46%；rd 4.33%；t 15%；账面权重）；增长 g0=0.0%（来源 none：资本腿 —=min(增量ROIC -6.5%,40%)×再投资率 -94%，增速腿 —），ROIC_T=min(WACC+档位超额, ROIC0)=9.1%，g_T=3.0%，fade 10 年，终值占比 64%；净负债/股 8.864（有息负债−超额现金＋少数股东权益）；**V = 21.062 USD/普通股** → **21.06 USD**；带 = V×[0.90,1.10]。标签：capex=PaymentsToAcquireProductiveAssets;cash=CashAndCashEquivalentsAtCarryingValue+CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents;cfo=NetCashProvidedByUsedInOperatingActivities+NetCashProvidedByUsedInOperatingActivitiesContinuingOperations;dep_amort=Depreciation;income_tax=IncomeTaxExpenseBenefit;interest_expense=InterestExpenseNonoperating+InterestAndDebtExpense;lt_debt_current=Lon
