# Moat Scoring Rubric

## 1. Purpose

This rubric defines the baseline full-coverage business-quality triage standard for listed companies in the A-share, Hong Kong, and U.S. universes. It is not a valuation model and does not produce buy recommendations.

The goal is to produce a first-layer triage signal with comparable dimensions, reliable public evidence, and explicit reasoning. ADR-0003 moves the canonical final watchlist decision to a two-layer company review, where companies with `triage_score >= 65`, companies marked `borderline`, and companies explicitly challenged by a reviewer receive a deep company review with common and special dimensions.

## 2. Scope

The baseline full-coverage triage runs apply to every eligible listed company or listed security represented in `data/raw/a_share_securities.csv`, `data/raw/hong_kong_securities.csv`, and `data/raw/us_securities.csv`.

For the U.S. universe, raw Nasdaq Trader data contains many non-company or non-common-equity instruments. ETF, ETN, unit, warrant, right, preferred, closed-end fund, and similar instruments should remain in the processed output with a not-applicable screening status, but they should not receive listed-company moat scores.

The raw universe remains immutable. Research queues, evidence summaries, triage scores, deep review outputs, and derived watchlists belong in `data/interim/` and `data/processed/`.

## 3. Evidence Standard

Each company should be scored from reliable public evidence, including annual reports, quarterly reports, exchange filings, official investor-relations materials, regulator disclosures, credible media, industry association data, and reputable research institutions.

For the deep-review layer introduced by ADR-0003, use company periodic reports, exchange announcements, regulator disclosures, official investor-relations materials, reputable institution reports, or professional research reports. Aggregator company introductions, including Eastmoney-style profile blurbs, can be used as discovery hints but must not be relied on as analysis evidence.

`insufficient_disclosure` is allowed only when all conditions hold:

1. The company has been listed for less than 12 months.
2. The company has not disclosed at least one annual report after listing.
3. Public filings, official materials, credible media, and reputable research institutions do not provide enough business description to support the rubric.

Missing local evidence rows, unsearched companies, or incomplete manual review are workflow states. They are not evidence insufficiency.

## 4. Capital Replicability Test

Every dimension should ask whether a well-funded new entrant could quickly win mainly by spending money.

High scores require evidence that capital alone is not enough because the company has hard-to-replicate advantages such as brand trust, customer relationships, licenses, regulated assets, scarce resources, proprietary technology, manufacturing know-how, supply-chain control, data network effects, ecosystem lock-in, or long clinical and quality-validation cycles.

Low scores indicate that a funded competitor could plausibly build similar capacity, hire similar teams, acquire traffic, open comparable outlets, copy products, or win customers without a long accumulation period.

## 5. Weighted Dimensions

Each dimension is scored from 0 to 100 and stored with two decimal places. The final score is the weighted sum stored with two decimal places.

| Dimension | Weight | Required CSV columns |
| --- | ---: | --- |
| Business moat and capital-replication resistance | 28% | `business_moat_score`, `business_moat_level`, `business_moat_reason` |
| Technology, product, process, or supply-chain barrier | 24% | `technology_barrier_score`, `technology_barrier_level`, `technology_barrier_reason` |
| Market position and competitive structure | 14% | `market_position_score`, `market_position_level`, `market_position_reason` |
| Business model quality | 8% | `business_quality_score`, `business_quality_level`, `business_quality_reason` |
| Operating and financial quality | 6% | `operating_quality_score`, `operating_quality_level`, `operating_quality_reason` |
| Industry outlook, cyclicality, and compounding profile | 14% | `industry_outlook_score`, `industry_outlook_level`, `industry_outlook_reason` |
| Governance, disclosure, and risk quality | 6% | `governance_risk_score`, `governance_risk_level`, `governance_risk_reason` |

## 6. Dimension Bands

Use the same score bands for every dimension.

| Band | Score | Meaning |
| --- | ---: | --- |
| S | 90-100 | Elite. A well-funded entrant cannot realistically replicate or overtake the company in a short period. |
| A | 80-89 | Strong. Capital helps competitors but important bottlenecks remain hard to buy quickly. |
| B | 70-79 | Clear advantage. The company has visible strengths, but determined competitors can narrow the gap over time. |
| C | 55-69 | Moderate. The company is viable, but a funded entrant with good execution could challenge it. |
| D | 40-54 | Weak. Advantages are limited and mostly replicable through capital, hiring, distribution, or normal execution. |
| E | 0-39 | Fragile. The company has little durable advantage or has severe operating, governance, or survival risk. |

## 7. Dimension Guidance

### 7.1 Business Moat And Capital-Replication Resistance

Score brands, channels, licenses, scarce assets, customer lock-in, network effects, switching costs, ecosystem control, and accumulated trust.

The core question is: if a new player had enough capital, could it enter this industry and beat this company mainly by spending money?

Current profit should not be used as a direct moat proxy. Losses, temporarily weak margins, or early ramp costs can lower business quality and operating quality, but they should not erase source-backed evidence of scarce resources, hard technology, long qualification cycles, process know-how, or regulatory/customer lock-in.

### 7.2 Technology, Product, Process, Or Supply-Chain Barrier

Score proprietary technology, patents, manufacturing process depth, product complexity, quality systems, engineering culture, data assets, supplier control, certification barriers, and time-to-scale.

The core question is: can a new player buy equipment and talent and quickly match the company's technical or operational capability, or are there learning curves and ecosystem constraints that capital cannot compress?

Do not treat R&D intensity as the only proxy for this dimension. For brand, food, beverage, consumer, and traditional manufacturing leaders, product formulation, origin constraints, long-cycle production process, quality systems, scarce capacity, channel control, and accumulated customer trust can create product or process barriers even when reported R&D intensity is low.

For advanced manufacturing leaders such as batteries, semiconductors, medical devices, robotics, and high-end equipment, explicitly score customer qualification cycles, safety validation, process yield, supply-chain orchestration, global delivery capability, and market-share leadership. A company with clear global leadership evidence should not be scored as only a generic manufacturing-scale business.

For strategic critical materials such as germanium, gallium, indium, tungsten, molybdenum, antimony, tantalum, rare metals, and compound-semiconductor materials, score resource access, purification, crystal growth, wafer or optical-material processing, standards participation, export-control relevance, and customer qualification as capability evidence. These companies remain cyclical, but they should not be treated as generic commodity producers when the evidence shows hard-to-replicate resource-plus-process capability.

For grid core equipment such as ultra-high-voltage transmission equipment, transformers, reactors, converter valves, HVDC systems, and integrated power-transmission engineering, score long engineering accumulation, safety validation, grid-customer qualification, first-set or demonstration-project references, and overseas project execution as technical and process barriers.

For food and beverage companies, separate ordinary recipe/process claims from scarce-origin and long-cycle production barriers. Top baijiu companies can deserve higher product/process scores when evidence shows origin scarcity, long-cycle brewing, base-liquor inventory, microbial or cellar-pool accumulation, quality consistency, and channel trust. Ordinary packaged food or condiment process language should receive a lower technical/process score unless the evidence shows similarly hard-to-replicate constraints.

### 7.3 Market Position And Competitive Structure

Score market share, rank, bargaining power, customer diversification, industry concentration, regulatory position, and ability to shape the category.

The core question is: does the company have an entrenched position in an attractive structure, or is it one of many interchangeable competitors?

### 7.4 Business Model Quality

Score recurring demand, pricing power, customer retention, unit economics, cyclicality, product mix, revenue durability, and dependence on subsidies or one-off project demand.

The core question is: can the company keep earning attractive business returns without constantly buying growth?

### 7.5 Operating And Financial Quality

Score cash conversion, margin profile, ROE or ROIC quality, balance-sheet pressure, working-capital discipline, capital intensity, earnings stability, and resilience through downturns.

The core question is: does the operating record support the claimed competitive strength, or does the business require heavy capital and favorable cycles to look good?

### 7.6 Industry Outlook, Cyclicality, And Compounding Profile

Score the structural demand outlook of the company's industry, whether the business is mainly cyclical or capable of internally controlled compounding, and whether future industry growth is likely to be captured by incumbents with real advantages.

This dimension must not become a momentum or valuation proxy. A hot industry with easy entry, fast capacity expansion, or frequent price wars should not receive an elite score merely because end-market demand is growing. A mature industry can still receive a good score when demand is durable, capital needs are moderate, pricing power exists, and leaders can compound cash flow.

Record `cyclicality_profile` and `compounding_profile` separately so reviewers can distinguish:

- Structural compounders such as software, dominant consumer brands, data ecosystems, and medical platforms.
- Structural-growth manufacturers with cycle risk such as batteries, semiconductors, automation, and renewable-energy equipment.
- Stable regulated assets such as utilities, pipelines, railways, ports, and water or gas concessions.
- Macro or credit cyclicals such as banks, insurers, brokers, and asset managers.
- Commodity cyclicals such as oil, gas, coal, metals, chemicals, paper, and upstream materials.
- Strategic resource-cycle leaders with scarce reserve ownership, reserve replacement capability, low-cost development, mine engineering/process know-how, and global portfolio integration.
- Property, construction, travel, leisure, retail, and other demand-cycle businesses.

The core question is: even if the industry grows, does this company have a realistic path to compound value through durable advantages, or will returns be competed away by capital, capacity, commodity prices, regulation, or macro cycles?

Commodity exposure should usually reduce compounding scores because price cycles can dominate earnings. However, do not treat every miner or upstream producer as interchangeable. A globally competitive resource owner/operator can deserve a higher moat, technology/process, and industry-outlook score when reliable evidence shows scarce reserves, reserve replacement, low-cost acquisitions, full-cycle mine development, low-grade or difficult-ore processing know-how, and the ability to improve acquired assets. The correct label for such cases is `strategic_resource_cycle`, not generic `commodity_cycle`.

### 7.7 Governance, Disclosure, And Risk Quality

Score governance quality, related-party risk, accounting transparency, regulatory exposure, safety or environmental risk, geopolitical risk, customer concentration, and disclosure reliability.

The core question is: can investors trust the public record enough to compare this company fairly, and are there structural risks that undermine otherwise strong business qualities?

## 8. Relative Peer Judgment

Each company should include `peer_group` and `peer_relative_position` using one of:

- `stronger_than_peers`
- `above_average`
- `average`
- `below_average`
- `weak`
- `hard_to_distinguish`

The peer comparison should use comparable listed companies or clear industry peers. When peers are hard to identify, record the reason rather than silently skipping the comparison.

## 9. Required Output Fields

The full-coverage processed CSV should preserve source security identifiers and add:

- `screening_status`
- `disclosure_status`
- `peer_group`
- `peer_relative_position`
- `cyclicality_profile`
- `compounding_profile`
- one score, level, and reason column for each weighted dimension
- `weighted_total_score`
- `overall_level`
- `overall_reason`
- `evidence_confidence`
- `source_urls`
- `reviewed_at_utc`
- `scoring_model_version`

## 10. Execution Plan

1. Remove tracked local skill files from Git and keep `.agents/` ignored.
2. Generate full A-share, Hong Kong, and U.S. research queues from the raw universes.
3. Collect source evidence for each listed company by filings, official materials, and authoritative external descriptions.
4. Normalize each company into a peer group.
5. Assign every dimensional score with a reason and sources.
6. Compute the weighted total from stored dimension scores, preserving two decimal places in each stored score.
7. Validate that every eligible raw A-share, Hong Kong, and U.S. row has either full dimensional scores or the narrow `insufficient_disclosure` status; U.S. non-company/non-common-equity instruments must have an explicit not-applicable status.
8. Run market-staged calibration: process A-share first, audit A-share triage coverage and reviewer-challenge routing, then use peer-group calibration to compare similar companies by industry before freezing reusable rules for Hong Kong and U.S. reviews.
9. Generate processed full-coverage outputs and a watchlist candidate view.

The full scores CSV remains security-level because raw universes are security-level. The compact watchlist view should be company-level where possible: if a market has duplicate currency counters, share classes, or otherwise duplicate listed-company identifiers, keep the full rows in the score output but keep one representative row in the watchlist.

## 10.1 Market-Staged Calibration Gate

Do not treat cross-market output as final while the review standard is still being challenged. A-share is the first calibration market. The A-share workflow gate should check:

- The run is scoped to `A_SHARE` only.
- Every eligible A-share listed company appears in the company-level triage output.
- Reviewer-challenged companies enter the deep-review queue even when their baseline triage scores are below threshold. These rows test routing only; they are not standard-setting anchors.
- Score-band distribution is visible for reviewer inspection, but no fixed candidate quota is imposed.

Passing this gate means the workflow has not structurally lost eligible A-share companies or reviewer challenges. It does not mean any challenged company has been finally accepted into the watchlist.

The actual standard-setting step is **Peer-Group Calibration**:

1. Choose one A-share industry or business type at a time.
2. Select multiple comparable listed companies from that peer group, including apparent leaders, second-tier companies, borderline companies, and companies that may be thematically attractive but weak in durable capability.
3. For each company, summarize the moat, business or technology barriers, market position, advantages, weaknesses, cyclicality, and preliminary attention decision using authoritative research sources.
4. Ask the reviewer to decide which companies deserve continued attention and which should be rejected, with reasons.
5. Translate the comparison into reusable industry-specific screening standards, including positive indicators, disqualifying weaknesses, and special dimensions.
6. Apply accepted A-share standards to Hong Kong and U.S. peer groups only after the A-share peer-group calibration is documented.

Peer-group calibration can use reviewer-challenged companies as ordinary examples when they belong to the selected industry, but it must not treat them as important merely because they were named earlier.

Reviewer feedback is a calibration input, not an automatic override. When source-backed evidence indicates that a rejected company has durable capability or market position that the feedback may underweight, record an explicit analyst dissent and the evidence basis before revising the rule.

When the reviewer is unfamiliar with a company but has provided a decision habit, infer the decision from that habit instead of marking the company unresolved. The current accepted habit is **Differentiated Peer Retention** plus the **Dominance Rejection Test**: keep multiple companies in a peer group only when each has a hard-to-replicate and meaningfully different advantage; reject companies that are comprehensively dominated by a retained peer and do not have an irreplaceable niche.

### 10.1.1 Accepted Baijiu Calibration

The first accepted A-share peer-group calibration is baijiu. The reviewer accepted baijiu as worth monitoring but assigned the industry a discounted long-term growth outlook because younger consumers drink less and may shift future gifting and beverage preferences away from traditional baijiu.

The accepted A-share baijiu watch group is limited to `贵州茅台`, `五粮液`, and `山西汾酒`. Other A-share baijiu companies, including strong regional leaders, former leaders, smaller companies, and turnaround or oversold-rebound candidates, should be rejected by default. The reason is not that these companies cannot rebound; it is that a weak long-term industry outlook makes second-tier and regional names poor uses of watchlist attention across a full cycle.

This rule can be overridden only when future evidence shows that a company has become a national or category-defining leader with durable pricing power, channel control, and resilience through a full downcycle.

### 10.1.2 Partial EV Battery Calibration

The second A-share peer-group calibration is power batteries and new-energy vehicle platforms. The accepted watch companies are `宁德时代` and `比亚迪`.

`亿纬锂能` was initially rejected because it lacked enough differentiated advantage versus `宁德时代`. That decision was revised on 2026-06-16 after official 2026H1 forecast evidence and reputable broker estimate summaries indicated stronger deducted-profit acceleration and a materially lower forward PEG. It is now retained as a weak L2 / boundary quasi-core watch company, below `宁德时代` and `比亚迪`, and must be downgraded again if the 2026H1 report does not validate operating cash flow, receivables, inventory, margin, and customer evidence.

`国轩高科`, `欣旺达`, `孚能科技`, `鹏辉能源`, and `珠海冠宇` are also rejected from the current power-battery and new-energy-platform watchlist under the **Dominance Rejection Test**. The reviewer did not know these companies well, but the accepted decision habit requires the analyst to reject weaker peers when the available evidence does not show a differentiated and hard-to-replace advantage versus `宁德时代` or `比亚迪`.

### 10.1.3 Accepted Medical-Device Calibration

The third A-share peer-group calibration is high-end medical devices and medical-device platforms. The accepted watch companies are `迈瑞医疗`, `联影医疗`, `惠泰医疗`, `心脉医疗`, and `南微医学`.

`迈瑞医疗` is retained as the broad medical-device platform example. `联影医疗` is retained as the high-end imaging example. `惠泰医疗`, `心脉医疗`, and `南微医学` are retained as specialized high-value device or consumable examples because their clinical niches are meaningfully different from the retained platforms and may have hard-to-replace doctor adoption, regulatory approval, recurring consumables, or treatment-pathway lock-in.

Medical-device tiering must distinguish platform breadth from specialized clinical depth. A broad platform deserves L1 only when the product lines share hospital channels, installed base, service network, global registration capability, R&D reuse, quality systems, and cash conversion. Product breadth becomes a downgrade signal if it dilutes ROIC, creates integration drag, hides weak franchises, or lets focused competitors take share. Specialized device companies such as electrophysiology, vascular intervention, high-end imaging, endoscopy, implant, biomaterial, or recurring-consumable leaders can remain L2 despite very high technical value when their standalone platform scale, cash-flow depth, or multi-cycle category dominance is still narrower than the L1 anchors.

Strategic acquisition by a broad platform is evidence that the target has meaningful clinical and technical value, but it is not sufficient by itself for L1. The target can be upgraded only after the acquisition or platform relationship demonstrably strengthens market share, global channel access, product adoption, margin durability, and cash-flow quality without making the target's thesis dependent on unproven synergy.

`开立医疗`, `新产业`, `乐普医疗`, and `新华医疗` are rejected from this group under the **Dominance Rejection Test** or because their current evidence does not prove a sufficiently irreplaceable niche. `鱼跃医疗` is rejected from this group and should be reclassified into a home-healthcare or consumer-medical-device peer group if reviewed later.

## 11. Calibration Notes

Model version `full_coverage_dimensional_v0.2` adds industry outlook as an explicit 10% dimension and reduces the other six weights proportionally. This was introduced after reviewing whether the earlier model could over-rank large cyclical companies and under-rank compound-growth companies with strong long-term demand but less stable current profitability.

The industry outlook dimension uses current public industry anchors only as broad calibration evidence, not as company-specific proof:

- IEA `Global EV Outlook 2025`: electric car sales exceeded 17 million in 2024, were expected to exceed 20 million in 2025, and the EV share was set to exceed 40% in 2030 under stated policies. This supports a structural-growth score for EV batteries and charging/storage ecosystems while still recognizing manufacturing-cycle and policy risk.
- IEA `Renewables 2025`: renewable power capacity additions for 2025-2030 were projected at about 4,600 GW, but the forecast was cut from the prior year because of policy, regulatory, and market changes. This supports structural demand for renewables while penalizing oversupply and policy-sensitive manufacturers.
- SIA/WSTS semiconductor data: 2025 global semiconductor sales rose 25.6% to $791.7 billion and 2026 sales were projected near $1 trillion, driven by logic, memory, AI, IoT, 6G, and autonomous-driving demand. This supports a structural-growth score for semiconductors while preserving semiconductor-cycle treatment.
- IMF `World Economic Outlook, April 2026`: global growth was projected at 3.1% in 2026 and 3.2% in 2027 with downside risks from conflict, fragmentation, AI-productivity disappointment, trade tensions, debt, and institutional vulnerabilities. This supports explicit discounts for macro, commodity, credit, property, travel, and discretionary demand cycles.

Reference URLs: `https://www.iea.org/reports/global-ev-outlook-2025/executive-summary`, `https://www.iea.org/reports/renewables-2025/renewable-electricity`, `https://www.semiconductors.org/global-annual-semiconductor-sales-increase-25-6-to-791-7-billion-in-2025/`, `https://www.imf.org/en/publications/weo/issues/2026/04/14/world-economic-outlook-april-2026`.

Model version `full_coverage_dimensional_v0.3` adds cross-market calibration for A-share scoring. The earlier A-share output had materially more high-score companies than the U.S. output, even though both universes had a similar number of scored companies. The audit found three mechanical causes: Eastmoney A-share profiles contain richer and more promotional business descriptions than the current SEC-derived U.S. profiles, generic words such as R&D, patents, innovation, and leading were over-rewarded, and local A-share peer-group percentiles allowed many domestic niche leaders to receive global-leader market-position scores.

The v0.3 A-share scorer therefore:

- Reduces generic profile keyword and listing-board bonuses.
- Removes non-moat keywords such as generic main-business or production-and-sales descriptions.
- Caps market-position scores for very small local peer groups.
- Applies an A-share cross-market calibration discount unless the evidence shows global leadership, scarce-resource control, regulated concessions, or strong brand/origin advantages.

This calibration is not a valuation view and does not say individual A-share leaders are weak. It prevents local evidence richness and local peer ranks from making the A-share high-score population structurally larger than the U.S. high-score population.

Model version `full_coverage_dimensional_v0.4` changes the model to capability-first scoring. The calibration review found that v0.3 still used current revenue, net profit, margins, ROE, and cash flow too strongly in the total score, which could exclude companies with source-backed hard capabilities but temporarily weak profitability. The updated weights therefore raise business moat, technology/process/supply-chain barrier, and industry outlook to 66% combined, and reduce business quality, operating quality, and governance/risk to 20% combined.

The v0.4 scorer keeps current profitability and cash conversion in the model, but mainly as maturity and risk constraints. A currently weak or loss-making company can enter a watchlist when reliable evidence shows hard-to-replicate capability, such as strategic critical materials, long-cycle food or beverage process barriers, UHV/grid-equipment qualification, battery/safety/process leadership, semiconductor or medical validation cycles, scarce resources, or customer/ecosystem lock-in. Conversely, companies with weak capabilities should not enter the watchlist merely because a favorable cycle temporarily lifts earnings.

The v0.4 review also adds explicit distinctions for:

- Strategic critical materials versus generic commodity producers.
- Global or national UHV/grid-equipment leaders versus generic electrical-equipment manufacturers.
- Top baijiu long-cycle origin/process barriers versus ordinary food and condiment process language.
- Governance/disclosure quality versus balance-sheet or capex-cycle pressure, so the score is not misread as a pure corporate-governance grade.
