# 1. A-Share Strategic Resources And Mining Peer-Group Calibration

> 历史行业校准记录：仅供追溯研究线索。当前名单、质量档及筛选规则读取工作流程与结构化真值；引用本页事实前须核对原始证据。

## 1.1 Purpose

This note starts A-share **Peer-Group Calibration** for strategic resources, mining, and basic-metal resource platforms.

The group is meant to fix a problem exposed by the baseline triage run: the old score over-rewarded revenue scale and industry labels, while under-rewarding hard-to-replicate resource development capability. In this group, `紫金矿业` and `洛阳钼业` should be judged as global resource developers, while `中国铝业`, `江西铜业`, and `云南铜业` should not automatically score higher just because their revenue base is large.

The key test is whether a well-funded new entrant can quickly defeat the company. In mining, capital is necessary but not sufficient: high-quality reserves, permits, geological knowledge, mine engineering, recovery-rate improvement, local government and community execution, and cross-border project management are not easy to buy quickly.

## 1.2 Evidence Boundary

This first pass uses company annual-report pages or annual-report PDFs where available, company official result releases, statutory disclosure media, reputable securities media reporting from annual reports, USGS mineral statistics, IEA critical-mineral analysis, and industry bodies such as the International Tin Association.

Rows using media annual-report summaries are acceptable for calibration discussion, but final deep review should replace them with direct annual-report PDFs, exchange filings, company sustainability reports, and detailed mine reserve or production disclosures.

## 1.3 Industry Context

Strategic resources are structurally different from consumer, software, and equipment companies. The advantage is often a scarce asset plus a development system, not a smooth compounding engine. The industry can deserve watchlist attention even when earnings are cyclical, but only when the company owns or controls hard-to-replace resource quality or processing capability.

IEA analysis says critical-mineral refining and processing have become more concentrated, and projects that China remains a dominant refined supplier for most minerals in the next decade. USGS Mineral Commodity Summaries 2026 provides the earliest comprehensive 2025 global production data for many relevant minerals. This supports a higher attention standard for copper, lithium, cobalt, rare earths, germanium, tin, tungsten, and related materials.

The same context argues for selectivity. A company should not enter the quality watchlist merely because the commodity price is rising. The evidence must show one or more of:

1. scarce reserve ownership or durable resource access;
2. proven low-cost or hard-ore development capability;
3. processing or separation know-how that capital cannot quickly replicate;
4. strategic position in a mineral with supply concentration or national-security relevance;
5. a differentiated role not already covered by a stronger retained peer.

## 1.4 Preliminary Attention Calls

| Tier | Companies | Preliminary Call |
| --- | --- | --- |
| Global resource-development anchors | 紫金矿业, 洛阳钼业 | Core watch |
| Strategic resource platforms | 北方稀土, 锡业股份 | Watch |
| Boundary strategic resources | 云南锗业, 盐湖股份 | Watch if strategic-resource thesis is accepted |
| Aluminum or tungsten boundary cases | 中国铝业, 厦门钨业, 中钨高新 | Boundary watch or reclassify |
| Copper smelting or weaker resource platforms | 江西铜业, 云南铜业 | Reject for now |
| Gold specialists | 山东黄金, 中金黄金 | Keep at most one pure-gold specialist if desired |
| Lithium and battery-material integration | 赣锋锂业, 天齐锂业, 华友钴业 | Reclassify to lithium or battery-materials groups before final decision |

The structured calibration table is `data/processed/a_share_strategic_resources_peer_group_calibration.csv`.

The structured reviewer decision table is `data/processed/a_share_strategic_resources_peer_group_decisions.csv`.

## 1.5 Reviewer Decision

Reviewer feedback explicitly retained:

- 紫金矿业
- 洛阳钼业
- 北方稀土
- 锡业股份

The reviewer then tightened the standard for boundary resource companies. Boundary decisions should test whether the company has a company-level international monopoly or near-monopoly position in its main business, high or structurally defensible margins, capacity constrained by scarce resources or formal quotas, cost competitiveness versus international peers, and enough reserve advantage to support long-term durability.

Boundary decisions under this stricter standard:

| Company | Decision | Reason |
| --- | --- | --- |
| 中国铝业 | Reject | Scale and integration are real, and China's electrolytic-aluminum capacity ceiling supports the industry, but company-level international monopoly and clear global low-cost evidence are insufficient. |
| 云南锗业 | Reject for now | Germanium is strategic and China is dominant, but authoritative evidence does not yet prove a strong enough company-level monopoly, reserve advantage, cost curve, or margin quality. |
| 盐湖股份 | Watch | Domestic strategic-resource position in potash and salt-lake lithium, very high margins, scarce brine resources, and permit/resource constraints justify retention despite no global potash monopoly. |
| 山东黄金 | Reject | Strong domestic gold miner, but gold mining is globally fragmented, profitability is heavily gold-price driven, and 紫金矿业 already covers a stronger diversified gold-resource thesis. |
| 厦门钨业 | Watch | Tungsten is supply-constrained and quota-controlled in China; the company has integrated tungsten-molybdenum operations, meaningful upstream self-supply, and high-value processing margins. |
| 中钨高新 | Watch | Annual-report evidence supports a hard-to-replicate tungsten platform, including Shizhuyuan and global No. 1 cemented-carbide scale; it is differentiated from 厦门钨业. |

Other preliminary rejects remain rejected: `江西铜业`, `云南铜业`, and `中金黄金`.

`赣锋锂业`, `天齐锂业`, and `华友钴业` are not decided in this group. They should be recalibrated in lithium-resource and battery-materials groups using the same monopoly, margin, capacity, cost, and reserve tests.

## 1.6 Accepted Calibration Rules

1. **Resource Watch Requires Scarcity Plus Capability**: reserve ownership alone is not enough. The company should also show development, processing, cost, recovery-rate, or integration capability.
2. **Global Mine Developers Outrank Smelting Scale**: `紫金矿业` and `洛阳钼业` should not be mechanically ranked below large aluminum or copper smelting platforms.
3. **Do Not Treat Revenue Scale As Moat**: large revenue from trading, smelting, or low-margin processing does not prove hard-to-replicate business strength.
4. **Company-Level Monopoly Matters More Than Country-Level Monopoly**: a country may dominate a mineral, but a listed company still needs evidence of company-level quota, reserve, market share, cost curve, or processing capability.
5. **Commodity Beta Is Not Enough**: gold, copper, aluminum, lithium, and rare-earth price exposure should not by itself create watchlist inclusion.
6. **Use Differentiated Peer Retention**: keep multiple resource companies only when each covers a distinct hard-to-replicate advantage, such as copper-gold global mine development, copper-cobalt-molybdenum multi-metal assets, rare-earth separation and quota, tin-indium resource leadership, or salt-lake potash and lithium.
7. **High Margins Need A Source**: margin quality should be tied to reserve quality, low-cost production, quota scarcity, high-value processing, or customer-validated materials capability, not only a favorable commodity price.
8. **Capacity Constraint Is Useful Only When It Is Company-Relevant**: industry caps support pricing, but watchlist inclusion requires the company to own scarce capacity, permits, brine, mine reserves, or processing know-how.
9. **Tungsten Can Retain More Than One Company**: `厦门钨业` and `中钨高新` are retained together because one is an integrated tungsten-molybdenum and materials platform, while the other is a Shizhuyuan-backed hard-alloy and tooling platform.
10. **Pure Gold Needs A Separate Thesis**: a gold company should be retained only if its mine assets, exploration, cost curve, or deep-mining capability are worth observing independently of gold price and not already covered by a stronger diversified miner.
11. **Cross-Industry Resource Packages Must Be Checked Before Final Rejection**: when a listed company combines multiple scarce-resource exposures, equity economics, controlling-shareholder operating capability, or differentiated processing systems, the final decision must consider the aggregate company-level thesis rather than only the narrow peer group where it was first compared.

## 1.7 Analyst Dissent Policy

1. I would strongly dissent if `紫金矿业` or `洛阳钼业` are rejected from resource watch solely because earnings are cyclical.
2. I would dissent if `北方稀土` or `锡业股份` are rejected without addressing their rare-earth and tin-indium resource positions.
3. I would now accept rejecting `云南锗业` for lack of company-level monopoly, reserve, cost, and margin evidence. I would still object if the only rejection reason is current profit weakness.
4. I would not defend `中国铝业` as a top-five A-share quality company under the current evidence. Industry capacity caps are not enough without company-specific low-cost and reserve proof.
5. I would dissent if `盐湖股份`, `厦门钨业`, or `中钨高新` are rejected without addressing their resource constraints, high margins, quota or capacity limits, and differentiated roles.
6. I would not dissent if `山东黄金`, `江西铜业`, `云南铜业`, or `中金黄金` remain excluded under the current evidence.

## 1.8 Remaining Work

1. Keep accepted decisions synchronized with `data/processed/a_share_peer_group_calibrated_watchlist.csv`.
2. Open separate peer groups for lithium resources and battery materials before deciding `赣锋锂业`, `天齐锂业`, and `华友钴业`.
3. When finalizing the A-share watchlist, correct the baseline triage bias that placed `中国铝业` and `云南铜业` too high relative to `紫金矿业` and `洛阳钼业`.
4. Replace media summaries with direct annual-report PDFs for every retained company before final deep-company review.
5. Recheck resource companies rejected inside a narrow peer group for cross-industry scarce-resource packages before final exclusion. `藏格矿业` is the accepted correction case from the later lithium-resource calibration.

## 1.9 Sources

- IEA critical minerals topic page and Global Critical Minerals Outlook 2025: `https://www.iea.org/topics/critical-minerals`, `https://www.iea.org/reports/global-critical-minerals-outlook-2025/overview-of-outlook-for-key-minerals`
- USGS Mineral Commodity Summaries 2026: `https://pubs.usgs.gov/publication/mcs2026`
- International Tin Association market analysis: `https://www.internationaltin.org/market-analysis/`
- 紫金矿业 annual-report page and 2025 result material: `https://www.zjky.cn/investor/year-report.jsp`, `https://www.zjky.cn/upload/file/2026/03/31/3659a099877a49eeb4abd49e1f0f2b96.pdf`
- 洛阳钼业 2025 result release: `https://www.cmoc.com/html/2026/News_0327/398.html`
- 中国铝业 2025 annual report page and PDF: `https://www.chalco.com.cn/tzzgx/thygg/202603/t20260330_166168.html`, `https://www.chalco.com.cn/tzzgx/thygg/202603/P020260330341392300660.pdf`
- 北方稀土 2025 annual-report entry and result coverage: `https://www.chinamoney.com.cn/chinese/cwbg/20260417/3318496.html`, `https://finance.sina.com.cn/stock/aiassist/yjbg/2026-04-17/doc-inhuvera3228248.shtml`
- 锡业股份 2025 annual-report coverage: `https://finance.sina.com.cn/jjxw/2026-03-30/doc-inhsttra9736735.shtml`
- 云南锗业 2025 annual-report coverage: `https://www.stcn.com/article/detail/3781793.html`, `https://www.stcn.com/article/detail/3781624.html`
- 厦门钨业 2025 annual report PDF: `https://pdf.dfcfw.com/pdf/H2_AN202604231821508158_1.pdf`
- 厦门钨业 2025 result and tungsten-quota coverage: `https://www.stcn.com/article/detail/3794833.html`, `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12165582&stockid=600549`
- 中钨高新 2025 annual report and ESG coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12202469&stockid=000657`, `https://wap.stockstar.com/detail/RB2026051300001897`
- 江西铜业 periodic-report page and result coverage: `https://www.jxcc.com/periodicReports.html`, `https://finance.sina.com.cn/roll/2026-03-26/doc-inhsiusn5818999.shtml`
- 云南铜业 2025 annual-report entry and result coverage: `https://www.chinamoney.com.cn/chinese/cwbg/20260327/3306213.html`, `https://finance.sina.com.cn/stock/aiassist/yjbg/2026-03-26/doc-inhsiusr8852538.shtml`
- 山东黄金 2025 annual report, result, and resource coverage: `https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12022632&stockid=600547`, `https://jjdb.sdenews.com/jjdb/jjdb/content/20260327/Articel01002MT.htm`, `https://www.cfi.net.cn/p20260326004883.html`
- 盐湖股份 2025 annual-report summary and research coverage: `https://static.cninfo.com.cn/finalpage/2026-03-31/1225061822.PDF`, `https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/search/rptid/829070079239/index.phtml`
- 赣锋锂业 2025 annual report and result coverage: `https://pdf.dfcfw.com/pdf/H2_AN202603301820873426_1.pdf`, `https://finance.sina.com.cn/jjxw/2026-03-31/doc-inhswttw2415457.shtml`
- 天齐锂业 2025 result coverage: `https://finance.sina.com.cn/stock/aiassist/yjbg/2026-04-27/doc-inhvxxxa9048538.shtml`
- 华友钴业 2025 result and strategic coverage: `https://www.huayou.com/news/press-release/697`, `https://www.huayou.com/news/press-release/698`
