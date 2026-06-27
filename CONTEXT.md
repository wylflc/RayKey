# AShareQuant

AShareQuant models listed-company research for mainland China, Hong Kong, and U.S. equity markets. This context keeps stable domain language separate from changing implementation plans and task-specific requirements.

## Language

**Listed Company**:
The business entity being researched, which may correspond to one or more tradable securities.
_Avoid_: stock, ticker, security when referring to the business entity.

**Security**:
A tradable instrument identified by exchange, symbol, share class, and market-specific identifiers.
_Avoid_: company when referring to the listed instrument.

**A-Share Security**:
A security listed on a mainland China exchange and traded under that market's rules.
_Avoid_: China stock when the exchange and share class matter.

**Hong Kong Security**:
A security listed on the Hong Kong market and traded under that market's rules.
_Avoid_: HK company when referring only to the instrument.

**U.S. Security**:
A security listed on a U.S. exchange and represented by its listing exchange, symbol, share class or security type, and provider identifiers.
_Avoid_: U.S. company when referring only to the listed instrument.

**Universe**:
The full set of listed securities eligible for a given analysis run.
_Avoid_: all stocks when eligibility rules are part of the meaning.

**Universe Snapshot**:
A timestamped capture of securities returned by a named data provider for a universe construction run, with source provenance retained for auditability.
_Avoid_: current stock list when provider and retrieval time matter.

**Watchlist**:
The set of listed companies retained for ongoing attention after business-quality screening.
_Avoid_: buy list, target list.

**Final Screening Result**:
A consolidated market-level screening output that contains one final attention decision per eligible listed company after triage, peer-group calibration, reviewer challenges, and any supplemental cleanup decisions have been resolved.
_Avoid_: leaving multiple split decision tables as competing sources of truth after a market review is complete.

**Watch Selection Route**:
A label showing whether a listed company entered a **Watchlist** as a direct reviewer-accepted watch company or as a boundary company retained after analyst judgment under calibrated rules.
_Avoid_: mixing explicit reviewer selections and analyst-inferred boundary decisions without traceability.

**Attention Class**:
The first-round, full-universe classification of a listed company into one of three lifecycle states — worth-attention, boundary-pending, or garbage — before any quality tiering. It decides whether a company stays in the research pool at all.
_Avoid_: quality tier, buy decision.

**Worth-Attention Company**:
A listed company the first round keeps for ongoing attention. The set of worth-attention companies is the **Watchlist**, and only these receive a **Quality Tier**.
_Avoid_: buy candidate, current holding.

**Boundary-Pending Company**:
A listed company not currently worth attention but eligible to re-enter review on a hard trigger such as a new product, customer validation, major order, restructuring, or industry-structure change. It carries no **Quality Tier** while pending.
_Avoid_: garbage, permanently rejected.

**Garbage Company**:
A listed company permanently excluded during the first round for absent durable quality or for governance/fraud reasons. It is removed from the pool and never re-screened on price, theme, or low PE; only its security master data is maintained.
_Avoid_: boundary-pending, temporarily out, L5.

**Quality Tier**:
An L1–L5 business-quality rank assigned only to **Worth-Attention Companies**, ignoring current price. L1–L4 are keeper tiers (L1 core candidate, L2 quasi-core candidate, L3 tactical candidate, L4 zero-position watch). L5 is not a keeper grade: it means the company no longer deserves worth-attention and is demoted to **Boundary-Pending**. Permanent removal is expressed through **Attention Class** (garbage), never through L5.
_Avoid_: using L5 to mean garbage; letting valuation move a tier.

**Moat Screening**:
Assessment of durable business advantages and resistance to competitive displacement.
_Avoid_: valuation screen, cheap-stock screen.

**Screening Evidence**:
Reliable source-backed information used to support a **Moat Screening** decision.
_Avoid_: unsourced notes, model guesses.

**Authoritative Research Source**:
A company filing, periodic report, exchange announcement, official investor-relations material, regulator disclosure, reputable institution report, or clearly attributed professional research report used as primary support for a company review.
_Avoid_: aggregator company introductions, scraped profile blurbs, unsourced summaries.

**Full-Coverage Screening Run**:
A screening run that attempts to score every eligible listed company in a universe with the same rubric, rather than only companies that were manually selected first.
_Avoid_: candidate sampling, partial watchlist when the run claims universe coverage.

**Two-Layer Company Review**:
A **Moat Screening** workflow with a broad first-layer triage across the universe and a second-layer deep review for companies that are retained, borderline, or explicitly challenged.
_Avoid_: treating a fixed-weight score as the final research judgment.

**Triage Review**:
A fast first-layer review that assigns a preliminary attention decision from limited but reliable evidence and routes companies to reject, borderline, or deep review.
_Avoid_: final score, full investment memo.

**Deep Company Review**:
A second-layer company-level review that reads authoritative sources, states a business thesis, tests counterarguments, scores common dimensions, and adds special dimensions where the company's real advantage is not captured by the common set.
_Avoid_: one-size-fits-all scoring row.

**Dimensional Score**:
A 0-100 score for one explicit screening dimension, such as business moat, technology barrier, market position, business quality, operating quality, industry outlook, or governance and risk quality.
_Avoid_: unweighted impression, single blended note.

**Special Dimension**:
A company-specific review dimension used in a **Deep Company Review** when a listed company's real advantage is specific to its business type, such as CRDMO platform depth, clinical adoption, vertical integration, scarce-origin brand power, or global resource development capability.
_Avoid_: forcing every company into the same fixed dimensions.

**Cyclicality Profile**:
A screening label that identifies whether a listed company's industry is mainly stable, structurally growing, macro-credit cyclical, commodity cyclical, property/rate cyclical, capex cyclical, or demand/policy cyclical.
_Avoid_: treating all growth industries or all current profit leaders as equally durable.

**Compounding Profile**:
A screening label that identifies whether a listed company has a plausible path to compound value through brand, data, innovation, regulated assets, installed base, balance-sheet discipline, or scale/process advantages.
_Avoid_: assuming high current revenue or a large addressable market automatically means compound growth.

**Strategic Resource Cycle**:
A cyclicality profile for resource companies that remain exposed to commodity prices but have non-generic advantages from scarce reserve ownership, reserve replacement, low-cost development, mine engineering, difficult-ore processing, or global asset integration.
_Avoid_: treating all miners or upstream producers as interchangeable commodity-cycle businesses.

**Cross-Market Calibration**:
A scoring adjustment used when evidence source richness, local peer-group definitions, or market structure would otherwise make scores from different exchanges non-comparable.
_Avoid_: forcing every market to have the same number of watchlist candidates or applying a valuation opinion inside moat screening.

**Market-Staged Calibration**:
A workflow for validating screening standards one market at a time before applying the accepted rules to another market.
_Avoid_: mixing A-share, Hong Kong, and U.S. outputs while the standard itself is still being challenged.

**Peer-Group Calibration**:
A standard-setting workflow that compares multiple similar listed companies in the same industry or business type, summarizes their moat, advantages, weaknesses, market position, and preliminary attention decision, then uses reviewer feedback to refine reusable screening standards.
_Avoid_: using a few familiar or randomly named companies as the standard anchor for an entire market.

**Cross-Industry Advantage Review**:
A secondary check in **Peer-Group Calibration** for listed companies that were judged inside one industry group but also have material hard-to-replicate assets, licenses, resource rights, equity interests, controlling-shareholder capability, or operating systems from another business line.
_Avoid_: rejecting a listed company only because it is weaker than the best peer in the current comparison group when its aggregate company-level advantage is materially different.

**Differentiated Peer Retention**:
A peer-group calibration rule that allows multiple listed companies in the same industry to remain on the watchlist only when each has a hard-to-replicate and meaningfully different advantage.
_Avoid_: retaining weaker peers merely because they also rank well or benefit from the same industry growth.

**Dominance Rejection Test**:
A peer-group calibration test that rejects a listed company when a stronger peer comprehensively dominates it across moat, technology or process capability, market position, customer validation, and business quality, and the weaker company lacks an irreplaceable niche.
_Avoid_: keeping a company because it is unfamiliar, second-tier, or might rebound without a distinct durable advantage.

**Low-Barrier Group Rejection**:
A peer-group decision that can reject every listed company in an industry or subindustry when the business model is easy for capital and management execution to copy, durable margins are weak, and incremental profit is likely to attract new competition.
_Avoid_: forcing at least one watchlist company to exist in every industry.

**Capability-First Scoring**:
A scoring stance for **Moat Screening** that gives primary weight to durable business capability, technical or process barriers, market position, and long-term industry outlook, while using current profitability, ROE, and cash flow as risk constraints rather than the main reason a company enters or leaves the **Watchlist**.
_Avoid_: treating current losses or weak margins as proof that a company lacks a moat when source-backed evidence shows hard-to-replicate capability.

**Capital Replicability Test**:
A way to evaluate competitive strength by asking whether a well-funded new entrant could quickly build the same capability, enter the industry, and overtake the listed company mainly through capital spending.
_Avoid_: assuming a business is strong only because it is large or profitable today.

**Insufficient Disclosure**:
A narrow screening status for a listed company that is too newly listed to have enough periodic reports and also lacks authoritative public business descriptions from filings, regulators, credible media, or research institutions.
_Avoid_: not yet researched, missing evidence row.

**Moat Score**:
A rough 0-100 quality score from **Moat Screening** based on source-backed evidence of business barriers, technical barriers, market position, cash flow quality, and margin quality.
_Avoid_: valuation score, buy score.

**Watchlist Candidate**:
A listed company or security that passes the current **Moat Screening** threshold and is worth later **Valuation Assessment**.
_Avoid_: buy candidate, undervalued stock.

**Investment Strategy Tag**:
A primary investment-case classification that selects the correct analysis and valuation lens for a listed company or security, such as cash-flow compounder, cigar-butt undervaluation, GARP growth, supply-chain breakout, fallen champion, monopoly resource, or shareholder-return undervaluation.
_Avoid_: industry label, theme label, price-action label.

**Valuation Assessment**:
Assessment of whether a security's current price is attractive relative to fundamentals or intrinsic value.
_Avoid_: moat screening.

**Scenario Valuation**:
A **Valuation Assessment** expressed as bear, base, and bull cases with explicit assumptions about demand, margins, capital intensity, valuation multiple, asset value, or cycle position.
_Avoid_: target price when assumptions are not stated.

**Position Plan**:
Non-binding portfolio guidance that maps a security's **Valuation Assessment**, thesis evidence, risk, and portfolio constraints to a suggested action or position range.
_Avoid_: buy order, guaranteed allocation.

**Market Data**:
Daily trading records such as open, high, low, close, volume, turnover, and trading status.
_Avoid_: financial data.

**Corporate Action**:
An issuer event that affects ownership, cash flows, or historical price comparability, such as dividends, splits, bonus shares, or rights issues.
_Avoid_: price data.

**Financial Report Data**:
Reported financial statements, key metrics, narrative disclosures, and their reporting periods.
_Avoid_: market data.

**Disclosure Timeline**:
Expected, preliminary, forecast, and official announcement dates for financial reporting events.
_Avoid_: report date when the specific event type matters.

## Relationships

- A **Listed Company** can have one or more **Securities**.
- A **Universe** contains **Securities**, but a **Watchlist** contains **Listed Companies**.
- A **Final Screening Result** is the structured source of truth for a completed market review; filtering it to `watch` decisions produces the current **Watchlist** for that market.
- A **Watch Selection Route** preserves whether a **Watchlist** entry came from direct reviewer acceptance or boundary-company judgment.
- A first-round **Attention Class** is assigned to every eligible listed company; only **Worth-Attention Companies** then receive a **Quality Tier**.
- The **Watchlist** is the set of **Worth-Attention Companies** currently tiered L1–L4. A **Quality Tier** of L5 demotes a company out of the **Watchlist** into **Boundary-Pending**; permanent **Garbage** removal happens only in the first round and is not reversible.
- A **Quality Tier** ranks business quality only; current price belongs to **Valuation Assessment** and must not move a tier.
- A **Universe Snapshot** records the **Securities** available from a provider at retrieval time and can be used as input to later screening.
- **Screening Evidence** supports a **Moat Score**; a high enough **Moat Score** can produce a **Watchlist Candidate**.
- **Authoritative Research Sources** are required for a **Deep Company Review**; aggregator profile text can only be used as a discovery hint, not as analysis evidence.
- A **Full-Coverage Screening Run** must produce at least a **Triage Review** for every eligible **Listed Company**, except the narrow **Insufficient Disclosure** case.
- A **Two-Layer Company Review** sends companies from **Triage Review** into **Deep Company Review** when the triage score is at least 65, the triage decision is borderline, or the company is explicitly challenged by a reviewer.
- A **Deep Company Review** can include **Special Dimensions** in addition to common public dimensions.
- A **Dimensional Score** should apply the **Capital Replicability Test** where relevant so the score reflects durable competitive strength rather than current size alone.
- **Capability-First Scoring** keeps **Moat Screening** focused on real competitive capability before valuation or short-term earnings normalization.
- **Cyclicality Profile** and **Compounding Profile** explain how the industry outlook contributes to **Moat Screening** without turning it into a valuation or market-momentum signal.
- A **Strategic Resource Cycle** company can enter a **Watchlist** if its resource and process advantages are strong enough, even though commodity prices still make its earnings cyclical.
- **Cross-Market Calibration** should correct mechanical scoring bias while preserving company-level evidence and dimensional score traceability.
- **Market-Staged Calibration** should validate one market's **Triage Review** and **Deep Company Review** behavior before turning the lessons into reusable rules for other markets.
- **Peer-Group Calibration** is the preferred way to form reusable standards: the reviewer compares similar listed companies first, then the accepted/rejected examples become standard-setting evidence.
- **Cross-Industry Advantage Review** should be applied before final rejection when a listed company has material assets or capabilities outside the selected peer group. Cross-industry breadth qualifies only when the aggregate company-level thesis is source-backed, material, hard to replicate, and not merely a conglomerate discount story.
- **Differentiated Peer Retention** and the **Dominance Rejection Test** should be applied together: keep multiple companies in one peer group only when their advantages are meaningfully different and hard to replace; reject a company when a stronger peer comprehensively covers its advantage.
- **Low-Barrier Group Rejection** is allowed when an entire peer group lacks durable barriers; peer-group calibration does not require every industry to contribute at least one **Watchlist** company.
- **Moat Screening** determines whether a **Listed Company** deserves attention; **Valuation Assessment** determines whether a **Security** may be attractively priced.
- An **Investment Strategy Tag** determines which evidence and valuation method should be used in a **Valuation Assessment**; it is not interchangeable with an industry label or short-term market theme.
- A **Scenario Valuation** supports a **Valuation Assessment** by making bear, base, and bull assumptions explicit before a security is considered for a **Position Plan**.
- A **Position Plan** belongs to a **Security** and is downstream of both **Moat Screening** and **Valuation Assessment**; it must not be treated as proof that the underlying **Listed Company** has a stronger moat.
- **Market Data** belongs to a **Security** and trading date.
- **Corporate Actions** belong to a **Security** or **Listed Company** and affect how **Market Data** should be interpreted.
- **Financial Report Data** belongs to a **Listed Company** and reporting period, with dates captured in the **Disclosure Timeline**.

## Example Dialogue

> **Dev:** "If a company passes moat screening, should it be marked as a buy?"
> **Domain expert:** "No. It enters the Watchlist. Buying requires a separate Valuation Assessment on the relevant Security."

## Flagged Ambiguities

- "Company" and "stock" are easy to conflate. Use **Listed Company** for the business entity and **Security** for the exchange-traded instrument.
- "Worth attention" is resolved as **Watchlist** inclusion based on **Moat Screening**, not as a purchase recommendation.
- "Position" and "watch" are easy to conflate. A **Position Plan** can recommend zero position, tactical monitoring, or a position range only after a separate **Valuation Assessment** on the relevant **Security**.
- "Evidence insufficient" is narrow. It does not mean a company has not yet been reviewed; it means the company lacks enough public disclosure and authoritative external description to support a fair score.
