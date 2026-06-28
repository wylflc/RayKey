# 1. A-Share Baijiu Peer-Group Calibration

## 1.1 Purpose

This note starts A-share **Peer-Group Calibration** for the baijiu industry. It is not a final watchlist and not a valuation view.

The goal is to compare similar listed companies side by side, state their apparent moat and weaknesses, make a preliminary attention call, and then use reviewer feedback to turn the comparison into reusable screening rules.

## 1.2 Evidence Boundary

This first pass uses annual-report disclosures, annual-report summaries from designated disclosure media or announcement mirrors, and the KPMG / China Alcoholic Drinks Association 2025 mid-term baijiu market report.

Aggregator company profile blurbs are not used as company-analysis evidence. Rows marked `needs_primary_pdf` in `data/processed/a_share_baijiu_peer_group_calibration.csv` should receive direct exchange or company annual-report PDFs before the rule is frozen.

## 1.3 Industry Context

The industry is in a deep adjustment period. The KPMG / China Alcoholic Drinks Association report describes policy adjustment, consumer-structure transition, and inventory pressure occurring together. It also reports that 2024 scale-above baijiu output declined while revenue and profit concentrated further in leading companies.

Two calibration implications follow:

1. A high-quality baijiu company should show brand pull, price discipline, channel control, and product quality barriers through the downturn.
2. Regional or old-brand companies should not be accepted just because they are listed baijiu companies; their local market share, channel health, price stability, and cash conversion need evidence.

## 1.4 Preliminary Attention Calls

| Tier | Companies | Preliminary Call |
| --- | --- | --- |
| National high-end or category leaders | 贵州茅台, 五粮液, 山西汾酒 | Core watch |
| Strong but needs operating verification | 泸州老窖, 古井贡酒, 今世缘, 迎驾贡酒 | Watch |
| Possible turnaround or rule-boundary cases | 洋河股份, 口子窖 | Watch only if channel and price-system repair is evidenced |
| Reject for now | 水井坊, 舍得酒业, 酒鬼酒, 老白干酒, 顺鑫农业, 金徽酒, 伊力特, 天佑德酒, 金种子酒, 皇台酒业, *ST岩石 | Do not include unless reviewer supplies stronger contrary evidence |

## 1.5 Reviewer Decision

Reviewer feedback accepts baijiu as an industry worth monitoring, but assigns it a weak long-term growth outlook. The key rationale is that younger consumers drink less, and their future gifting choices and beverage preferences may gradually pressure baijiu demand. The short-term impact may be limited, especially for high-end baijiu, but the secular risk should narrow the attention list.

Accepted watch companies:

- 贵州茅台
- 五粮液
- 山西汾酒

Rejected after reviewer calibration:

- 泸州老窖
- 古井贡酒
- 洋河股份
- 今世缘
- 迎驾贡酒
- 口子窖
- 水井坊
- 舍得酒业
- 酒鬼酒
- 老白干酒
- 顺鑫农业
- 金徽酒
- 伊力特
- 天佑德酒
- 金种子酒
- 皇台酒业
- *ST岩石

The reviewer explicitly rejected the idea that smaller baijiu companies deserve attention because of oversold rebounds. The calibrated standard is that these companies can rebound during favorable windows but are likely to fall back during the next baijiu downcycle, so they should not consume watchlist attention.

The structured reviewer decision table is `data/processed/a_share_baijiu_peer_group_decisions.csv`.

## 1.6 Accepted Baijiu-Specific Rules

1. Baijiu is a mature, culturally entrenched industry with real moat in leading brands, but its long-term growth outlook should be discounted because generational consumption and gifting preferences may shift away from the category.
2. Only national top leaders or category-defining leaders should enter the watchlist.
3. For the current A-share baijiu peer group, the watchlist is limited to `贵州茅台`, `五粮液`, and `山西汾酒`.
4. Regional leaders, former leaders, small-cap baijiu companies, and turnaround candidates should be rejected by default even when their local brand or short-term rebound potential is visible.
5. A non-top-three baijiu company can override this rule only if future evidence shows it has become a national/category leader with durable pricing power, channel control, and resilience through a full downcycle.

## 1.7 Original Rule Hypotheses

These are hypotheses for reviewer challenge, not final rules.

1. **Core Watch** requires at least one of:
   - National high-end price anchor with strong consumer pull and hard-to-replicate origin/process/brand trust.
   - Category-defining national leader whose brand and channel control remain resilient in downturns.
2. **Watch** can include strong regional leaders when:
   - The company has a dominant local banquet or gift-giving ecosystem.
   - Channel inventory and terminal pricing remain controlled.
   - The company can compound without relying mainly on channel stuffing or price-band expansion.
3. **Reject For Now** should apply when:
   - Advantage is mostly an old brand story without current pricing power.
   - The company is a small regional player facing stronger local or national brands.
   - The company is concentrated in the most pressured price band and lacks evidence of channel repair.
   - Governance, risk-warning, or non-core business issues undermine comparability.

## 1.8 Resolved Reviewer Questions

1. `贵州茅台`, `五粮液`, and `山西汾酒` are retained as the baijiu watch group.
2. `泸州老窖` is rejected despite strong brand assets because the reviewer wants only the top leaders in a weak long-term growth industry.
3. `古井贡酒`, `今世缘`, and `迎驾贡酒` are rejected because regional leadership is not enough under the accepted baijiu standard.
4. `洋河股份` and `口子窖` are rejected; repair or rebound potential is not sufficient.
5. Smaller regional, ST, and problem companies are rejected by default.

## 1.9 Sources

- KPMG and China Alcoholic Drinks Association, 2025 China Baijiu Market Mid-Term Research Report: `https://assets.kpmg.com/content/dam/kpmg/cn/pdf/zh/2025/06/mid-term-research-report-on-the-chinese-baijiu-market-2025.pdf`
- 贵州茅台 2025 annual report: `https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/listedinfo/announcement/c/new/2026-04-17/600519_20260417_9QS4.pdf`
- 五粮液 2025 annual-report disclosure summary: `https://paper.cnstock.com/html/2026-05/06/content_2212529.htm`
- 泸州老窖 2025 half-year report and 2025 annual-report mirror: `https://disc.static.szse.cn/disc/disk03/finalpage/2025-08-30/9b7b5a04-d2f1-4f2b-ac1d-35d1a6cb25de.PDF`, `https://pdf.dfcfw.com/pdf/H2_AN202604281821699992_1.pdf`
- 古井贡酒 2025 annual-report text mirror: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12258306&stockid=000596`
- White-liquor annual-report compilation used only as a secondary checklist for smaller companies: `https://fsc.foodmate.net/show.php?itemid=742696`

## 1.10 New-Standard Recalibration (ADR-0006)

The round-1 three-class standard (operation-workflow §5.4, ADR-0006) is competitiveness / capital-replicability based and does not exclude on industry growth outlook at round-1. Re-applying it to baijiu supersedes the earlier top-three reviewer call in §1.5–§1.8: the secular-growth concern is no longer a round-1 excluder but a discount applied later at L1–L5 tiering and valuation. The bar for `worth_attention` is that the moat is durable AND demonstrated through a full downcycle.

Calibrated round-1 result (written to `data/processed/a_share_attention_triage.csv`):

| Class | Companies | Basis |
| --- | --- | --- |
| worth_attention (5) | 贵州茅台, 五粮液, 山西汾酒, 泸州老窖, 洋河股份 | National leader or irreplaceable old-cellar/category brand; moat proven through cycles. 洋河 is a fallen champion with intact moat. |
| boundary_pending (14) | 古井贡酒, 今世缘, 迎驾贡酒, 口子窖 (strong regional, downcycle resilience unproven); 水井坊, 舍得酒业, 酒鬼酒, 老白干酒, 金徽酒, 伊力特, 天佑德酒, 金种子酒 (smaller / niche / weaker); 顺鑫农业 (real 牛栏山 moat but non-core drag); *ST椰岛 (chronic-loss *ST, fraud not confirmed) | Reversible; re-review on proven downcycle resilience, restructuring, or new reliable evidence. |
| garbage / governance_fraud (2) | 皇台酒业, *ST岩石 | Documented financial-fraud / governance-disaster history; confirm against filings before freezing. |

Generalizable rules distilled into operation-workflow §5.4.5: moat must be proven through a cycle; growth outlook is a tiering/valuation discount, not a round-1 excluder; heritage brand is a capital-replication-resistant moat; ST/distress from chronic losses without confirmed fraud is not garbage; diversified drag goes to boundary.
