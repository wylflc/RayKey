# 英伟达（NVDA）估值档案

> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。

- 质量档：**L1**｜参考分 **88.20**（Q1 90 / Q2 90 / Q3 84 / Q4 86，可信度扣分 0）
- 旗标：strategic_asset=AI 算力事实标准; erosion_path=客户自研 ASIC 与 AI 资本开支周期回落（中概率，2-3年可见）; special_advantage_check=CUDA 软件生态，计入 Q2

## 合理价区间

**237.33 ~ 303.25**

**方法**：PEG×ROE修正：PEG 1.5 × 增速 20.0% → PE 30.0x

**推导**：锚 = FY2027E EPS $8.79（一致预期；FY2027 为当前在途财年，对应日历 2026）（每股 8.79）；增速 20.0%（从一致预期 FY2028 +38% 大幅下折至 20%：AI 资本开支的可持续性是本 thesis 的核心风险，超大规模厂商的折旧压力与自研 ASIC 分流都在 2-3 年窗口内；§6.5.3 要求增速自行拆解，不采用券商 CAGR）；ROE 76.3% ≥40%，存量特许经营权占价值比重最高，PEG 取判例上限 1.5；PE = 1.5 × 20 = 30.0x；合理价 = 8.79 × 30.0 = 263.70，× 分层系数 [0.9, 1.15]（L1）= 237.33~303.25。**通用口径为何不成立**：原带「正常化 EPS $10.5 × 合理PE 27x」中 27x 无任何推导，属 §6.5.7 v1.54 禁止的直接指定；本档改由 ROE 76.3% 推出 PEG 1.5 再乘下折后的增速。交叉校验：隐含 PE 30x 对应 FY2027E，与原带 27x 同量级——但本档 PE 是算出来的。风险方向：若 AI 资本开支在 2027 年转入消化期，g 须下修至 10% 以下，带随之腰斩

## 参考分理由（§5.7.4）

Q1 90：无晶圆厂模式、极高毛利、预付款与长约锁定。Q2 90：CUDA 生态的软件锁定 + 系统级（NVLink/网络）整合，是资本短期难以复制的壁垒。Q3 84：回购与分红稳健，但巨额现金的长期配置路径尚待验证。Q4 86：创始人主导、技术判断长期领先，披露清晰。

## 跟踪指标

数据中心分部季度营收同比（阈值：连续两季环比下滑即下修 g 至 10%）；超大规模厂商合计资本开支指引；毛利率（阈值：<70% 预警）；客户集中度（前四大占比）；库存与采购承诺

## 复核触发

每季财报；超大规模厂商资本开支指引调整；出口管制政策变化；主要客户自研 ASIC 的量产进展

---
定档人：模型推导（用户可覆盖）｜复核日：2026-08-03

## ROIC 口径估值（§6.5.2.3 同口径）

证据 2026-08-26（二季报（FY2027Q2））。方法：ROIC·增长（§6.5.2.3 同口径）；带 77.97~95.29 USD。

ROIC·增长（§6.5.2.3 同口径，财年 2022~2026＋截至 2026-07-26 TTM，SEC companyfacts 10-Q TTM）：每股 NOPAT 锚（v4.47 OI-082：各年 NOPAT ÷ 最新稀释股数 24,285m）序列 0.41／0.18／1.23／3.01／4.95／7.96 → 取 **4.047**（blend(λ=1.0,w=0.79,v=0.00)）；周期守卫 NOPAT/(权益＋累计回购 96.6b)：最新 0.594 vs 10 年中位 0.335 = 1.77×，坡道 w=0.79／谷 v=0.00；信任度 λ=1.0，非周期锚 = 三年中位 4.953 + λ×(当期 − 三年中位) = 7.958，五年中位 3.010，锚 = (1−max(w,v))×非周期锚 + max(w,v)×五年中位；最新观察点回购 55.3b；BPS 9.43；ROIC0 124.4%；WACC 7.94%（r 8.80% = rf 4.79% + β0.9×ERP 4.46%；rd 2.59%；t 16%；账面权重）；增长 g0=25.0%（来源 trailing：资本腿 0.8%=min(增量ROIC 105.5%,40%)×再投资率 2%，增速腿 28.8%=CAGR 137.5%×(1−w 0.79)×d 1.00），ROIC_T=min(WACC+档位超额, ROIC0)=13.9%，g_T=3.0%，fade 10 年，终值占比 72%；净负债/股 -0.665（有息负债−超额现金＋少数股东扣减，扣减取账面与账面份额×权益价值较大者）；**V = 86.632 USD/普通股** → **86.63 USD**；带 = V×[0.90,1.10]。标签：buybacks=PaymentsForRepurchaseOfCommonStock;capex=PaymentsToAcquireProductiveAssets;cash=CashAndCashEquivalentsAtCarryingValue;cash_invest=DebtSecuritiesCurrent;cfo=NetCashProvidedByUsedInOperatingActivities;dep_amort=DepreciationDepletionAndAmortization;dividends_paid=PaymentsOfDividends;income_tax=IncomeTaxExpenseBenefit;interest_expense=InterestExpenseNonoperating;lt_debt_current=LongTermDebtCu
