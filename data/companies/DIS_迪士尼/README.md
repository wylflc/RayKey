# 迪士尼（DIS）估值档案

> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。

- 质量档：**L2**｜参考分 **70.70**（Q1 70 / Q2 78 / Q3 62 / Q4 64，可信度扣分 0）
- 旗标：erosion_path=线性电视持续衰退且流媒体盈利能力上限未知（高概率，已发生）; governance_open_issue=继任计划反复; special_advantage_check=IP 库与乐园实物资产，计入 Q2

## 合理价区间

**89.9 ~ 111.06**

**方法**：派息折现隐含PE：分红率/(r−g) = 56%/(8.5%−5.0%) = 15.9x

**推导**：锚 = FY2026E 调整后 EPS $6.64（公司 FY2026 指引：调整后 EPS 同比约 +12%、**剔除第 53 周**；一致预期 $6.83 为含第 53 周口径，按 §6.4 取剔除口径——第 53 周是日历一次性，不进稳态锚。原锚 $6.70 定于 FQ3 披露前，取的是两者之间的估计值）（每股 6.64）；分红率 56%（可持续口径 1 − g/ROE = 1 − 5.0%/11.3%）；可持续增长 5.0%（乐园与体验业务稳态个位数增长 + 流媒体转盈；线性电视持续衰退构成对冲，合计取 5%）；ROE 11.3%（10-K FY2025 11.3%，本仓库 us_financial_indicators.csv）；r = 8.5%（账户级要求回报）→ PE = 0.56/(0.085−0.050) = 15.9x；合理价 = 6.64 × 15.9 = 105.77，× 分层系数 [0.85, 1.05]（L2）= 89.90~111.06。**通用口径为何不成立**：ROE 11.3% <12%，OI-005 判据按定义不适用，且增长不再是主要价值来源——价值集中在乐园与 IP 的稳态现金产出，故走派息折现隐含 PE。原带「修复后合理PE 15-18x」只有定性理由（乐园+IP 现金流稳定，线性衰退折价），属直接指定。交叉校验：可持续派息率 55.8% 与其恢复派息后的实际分配能力方向一致；隐含 PE 15.9x 与原带 15-18x 重叠，但本档是算出来的

## 参考分理由（§5.7.4）

Q1 70：乐园重资产、内容投入刚性，但 IP 授权与体验业务定价权强。Q2 78：IP 库（漫威/皮克斯/星战）与乐园资产是真正难复制的资产，这是它仍在 L2 的原因。Q3 62：流媒体转型期的巨额内容投入回报未验证，历史并购（福克斯）回报差。Q4 64：CEO 继任问题反复、战略摇摆，是主要扣分项。

## 跟踪指标

体验分部（乐园+邮轮）经营利润（阈值：同比转负即下修 g）；流媒体分部经营利润率；线性电视收入衰退斜率；ROE（阈值：<8% 重估）；内容资本开支

## 复核触发

每季财报；乐园客流与定价数据；流媒体订阅数与提价执行；重大内容投资或并购；继任者交接进展

---
定档人：模型推导（用户可覆盖）｜复核日：2026-08-07

## ROIC 口径估值（§6.5.2.3 同口径）

更新 2026-08-23（`scripts/build_overseas_roic_bands.py`）。方法：ROIC·零增长（§6.5.2.3 同口径）；带 10.24~12.51 USD；审定档 高估。

ROIC·零增长（§6.5.2.3 同口径，财年 2021~2025，SEC companyfacts us-gaap）：NOPAT/母公司权益 比率 0.046（cyclical_median，周期守卫命中）× BPS 60.67 = NOPAT/股 2.786；ROIC0 3.1%；WACC 7.94%（r 9.20% = rf 4.74% + β1.0×ERP 4.46%；rd 4.50%；t 0%；账面权重）；零增长：V = NOPAT/股 ÷ WACC − 净负债/股；净负债/股 23.723（有息负债−超额现金＋少数股东权益）；**V = 11.373 USD/普通股** → **11.37 USD**；带 = V×[0.90,1.10]。标签：capex=PaymentsToAcquirePropertyPlantAndEquipment;cash=CashAndCashEquivalentsAtCarryingValue+CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents;cfo=NetCashProvidedByUsedInOperatingActivities+NetCashProvidedByUsedInOperatingActivitiesContinuingOperations;dep_amort=DepreciationDepletionAndAmortization+Depreciation;income_tax=IncomeTaxExpenseBenefit;interest_expense=InterestExpense;lt_debt_
