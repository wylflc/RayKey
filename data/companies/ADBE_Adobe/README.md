# Adobe（ADBE）估值档案

> 海外关注清单（§6.8）。**一律不可买、不构成买入候选**——本档只回答「质量几档、该用什么模型、现价贵不贵」，不进 §8 扫描、不走 §10 闸门。

- 质量档：**L2**｜参考分 **78.80**（Q1 84 / Q2 76 / Q3 80 / Q4 76，可信度扣分 0）
- 旗标：erosion_path=生成式 AI 对中低端创意工作流的替代（中概率，2-3年可见）; special_advantage_check=PDF/PSD 文件格式事实标准，计入 Q2

## 合理价区间

**424.52 ~ 518.85**

**方法**：三阶段DDM：3年@5.0% → 5年线性衰减 → 永续 3%，r=8.5%

**推导**：E0 = FY2026E non-GAAP EPS $24.40（公司指引 $24.35-24.45）（每股 24.40）；分红率 90%（无股息但几乎全部 FCF 用于回购（FY2026E FCF 约 $95亿），按「股息+净回购」口径计）；ROE 61.3%（10-K FY2025 61.3%，本仓库 us_financial_indicators.csv）；终值期分红率 = 1 − 3%/61.3% = 95.1%；g1 = 5.0%（AI 原生工具对中低端创意工作流的替代是本档核心风险，**该风险全部由 g 承担**（§15.2 只保守一次，不再另加倍数折价）：订阅 ARR 增速若维持则 g 回到 10%，故取 5% 为已计入替代冲击的中性假设，取一致预期窗口 3 年不外推）；现值 = 471.68（隐含 PE 19.3x），× [0.9, 1.1]（现值锚不叠加安全边际）= 424.52~518.85。**通用口径为何不成立**：ROE 61.3% 而增速 10%，命中 OI-005「ROE ≥20% 档 CAGR <15% 即 PEG 失效」；且 g 10% > r 8.5% 使单阶段戈登失效。原带「13-16x = 对 10年PE中位 28x 给 43-54% 折价」既用历史中位又叠加定性折价，两次保守（§15.2 保守叠加）。交叉校验：本档隐含 PE 显著高于原带的 13-16x——差异来源是原带对 AI 替代风险做了 43-54% 的定性折价。该风险本档不通过压倍数表达，而通过 g 已下修至 10% 与下方 key_metrics 的净新增 ARR 阈值承担（§15.2：只保守一次）

## 参考分理由（§5.7.4）

Q1 84：订阅制递延收入、极高毛利、近零边际成本。Q2 76：创意专业人群的工作流锁定与文件格式事实标准仍强，但生成式 AI 首次让低端替代成为可能——这是护城河的真实变数。Q3 80：回购纪律稳定、并购克制（Figma 收购受阻后未追高）。Q4 76：管理层稳定，指引可信度高。

## 跟踪指标

数字媒体 ARR 净新增（阈值：连续两季同比下滑即下修 g 至 5%）；订阅续费率；AI 功能付费渗透率；回购执行额（阈值：<$70亿 即下修分红率）；经营利润率

## 复核触发

每季财报与指引；生成式 AI 竞品的重大功能发布或价格战；ARR 增速跌破 8%；回购计划变更

---
定档人：模型推导（用户可覆盖）｜复核日：2026-08-03

## ROIC 口径估值（§6.5.2.3 同口径）

更新 2026-08-23（`scripts/build_overseas_roic_bands.py`）。方法：ROIC·增长（§6.5.2.3 同口径）；带 223.55~273.22 USD；审定档 较高估。

ROIC·增长（§6.5.2.3 同口径，财年 2021~2025，SEC companyfacts us-gaap）：每股 NOPAT 锚（v4.47 OI-082：各年 NOPAT ÷ 最新稀释股数 427m）序列 11.52／11.35／12.92／13.34／17.20 → 取 **17.201**（ttm_growth）；周期守卫 NOPAT/(权益＋累计回购 45.7b)：最新 0.128 vs 10 年中位 0.155（未命中）；最新年回购 11.3b；BPS 27.22；ROIC0 43.9%；WACC 6.98%（r 9.20% = rf 4.74% + β1.0×ERP 4.46%；rd 3.46%；t 18%；账面权重）；增长 g0=10.1%（来源 trailing：资本腿 —=min(增量ROIC —,40%)×再投资率 -10%，增速腿 10.1%），ROIC_T=min(WACC+档位超额, ROIC0)=10.0%，g_T=3.0%，fade 10 年，终值占比 82%；净负债/股 0.212（有息负债−超额现金＋少数股东权益）；**V = 248.386 USD/普通股** → **248.39 USD**；带 = V×[0.90,1.10]。标签：buybacks=PaymentsForRepurchaseOfCommonStock;capex=PaymentsToAcquirePropertyPlantAndEquipment;cash=CashAndCashEquivalentsAtCarryingValue+CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents;cash_invest=ShortTermInvestments;cfo=NetCashProvidedByUsedInOperatingActivities;dep_amort=DepreciationDepletionAndAmortization+DepreciationAndAmortization;income_tax=IncomeTaxExpenseBenefit;interest_exp
