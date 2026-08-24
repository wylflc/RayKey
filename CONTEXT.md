# AShareQuant

AShareQuant models listed-company research for mainland China, Hong Kong, and U.S. equity markets. This file holds stable domain language only. Executable standards live in `docs/000_Ashare_workflow.md`; investment judgment standards live in `docs/000_personal-investment-system-v1.zh.md`.

## Entities

**Listed Company** — the business entity being researched. It may correspond to one or more tradable securities. Distinct from **Security**: use *listed company* for the business, *security* for the exchange-traded instrument.

**Security** — a tradable instrument identified by exchange, symbol, share class, and market-specific identifiers. **A-Share**, **Hong Kong**, and **U.S. Securities** are the market-specific cases; the exchange and share class are part of the identity, not incidental labels.

**Universe** — the full set of listed securities eligible for a given analysis run. Eligibility rules are part of the meaning.

**Universe Snapshot** — a timestamped capture of securities returned by a named provider, with source provenance retained for auditability.

## Attention And Quality

**Attention Class** — the first-round, full-universe classification of a listed company into one of three lifecycle states, assigned before any quality tiering. It decides whether a company stays in the research pool at all, and is a separate decision from **Quality Tier** (ADR-0005).

- **Worth-Attention Company** — kept for ongoing attention. This set *is* the **Watchlist**, and only these receive a **Quality Tier**.
- **Boundary-Pending Company** — reviewable but off the watchlist, for one of two reasons: reliable evidence is insufficient to judge it (including a new listing without an annual report), or it is judgeable but currently lacks a durable advantage while its industry is not structurally hopeless. Carries no quality tier; re-enters review when reliable evidence appears or a hard trigger occurs (new product, customer validation, major order, restructuring, industry-structure change) — never on price action alone.
- **Garbage Company** — permanently excluded, and only for a governance/fraud disaster or an industry structurally low-barrier enough that no company can build a durable advantage. Company-level weakness in a non-hopeless industry is boundary-pending, not garbage. Never re-screened on price, theme, or low PE; only security master data is maintained. One narrow correction path exists (`garbage_review`, back to boundary-pending) — see workflow §5.5.

**Watchlist** — the set of listed companies retained for ongoing attention after business-quality screening. Not a buy list: watchlist membership says the business deserves attention, not that the security is worth owning.

**Quality Tier** — a business-quality rank assigned only to worth-attention companies, ignoring current price. Current price belongs to **Valuation Assessment** and must never move a tier. Permanent removal from research is expressed through **Attention Class**, not through a tier. Tier definitions and the tier's exact relationship to watchlist membership are governed by workflow §5.7/§5.8. The scored three-tier redesign went live on 2026-08-01 (workflow v1.27); its design trail is archived at `docs/archive/Ashare_tiering_v2_design.md`.

**Insufficient Disclosure** — a narrow status for a company too newly listed to have enough periodic reports *and* lacking authoritative public business descriptions. It does not mean "not yet reviewed".

## Screening

**Moat Screening** — assessment of durable business advantages and resistance to competitive displacement. Determines whether a listed company deserves attention; **Valuation Assessment** separately determines whether a security may be attractively priced.

**Screening Evidence** — reliable source-backed information supporting a moat-screening decision.

**Authoritative Research Source** — a company filing, periodic report, exchange announcement, official investor-relations material, regulator disclosure, reputable institution report, or clearly attributed professional research report. Aggregator company introductions and scraped profile blurbs are discovery hints, never analysis evidence.

**Capital Replicability Test** — asking whether a well-funded new entrant could quickly build the same capability, enter the industry, and overtake the company mainly through capital spending. Size and current profitability are not themselves evidence of strength.

**Capability-First Scoring** — giving primary weight to durable capability, technical or process barriers, market position, and long-term industry outlook, while using current profitability, ROE, and cash flow as risk constraints rather than the main reason a company enters or leaves the watchlist.

**Cyclicality Profile** — whether a company's industry is mainly stable, structurally growing, macro-credit cyclical, commodity cyclical, property/rate cyclical, capex cyclical, or demand/policy cyclical.

**Compounding Profile** — whether a company has a plausible path to compound value through brand, data, innovation, regulated assets, installed base, balance-sheet discipline, or scale/process advantages. A large addressable market is not itself a compounding path.

**Strategic Resource Cycle** — a cyclicality profile for resource companies still exposed to commodity prices but holding non-generic advantages: scarce reserve ownership, reserve replacement, low-cost development, mine engineering, difficult-ore processing, or global asset integration. Not interchangeable with generic commodity producers.

## Peer-Group Calibration

**Peer-Group Calibration** — the standard-setting workflow: compare multiple similar companies in one industry or business type, summarize each one's moat, advantages, weaknesses and market position, then turn the reviewer's accepted and rejected examples into reusable screening standards. Preferred over anchoring a market on a few familiar names.

**Differentiated Peer Retention** — keep multiple companies from one peer group only when each has a hard-to-replicate and meaningfully different advantage.

**Dominance Rejection Test** — reject a company when a stronger peer comprehensively dominates it across moat, technology or process capability, market position, customer validation, and business quality, and the weaker company lacks an irreplaceable niche.

**Low-Barrier Group Rejection** — an entire peer group may be rejected when the business model is easy for capital and execution to copy. No rule requires every industry to contribute a watchlist company.

**Cross-Industry Advantage Review** — before finally rejecting a company judged inside one peer group, check for material hard-to-replicate assets, licences, resource rights, equity interests, or operating systems from another business line. Qualifies only when the aggregate company-level thesis is source-backed and material, not a conglomerate-discount story.

## Valuation And Action

**Investment Strategy Tag** — the primary investment-case classification that selects the correct analysis and valuation lens (cash-flow compounder, cigar-butt undervaluation, GARP growth, supply-chain breakout, fallen champion, monopoly resource, shareholder-return undervaluation). It is not an industry, theme, or price-action label, and it determines which valuation method applies.

**Valuation Assessment** — whether a security's current price is attractive relative to fundamentals or intrinsic value.

**Scenario Valuation** — a valuation assessment expressed as bear, base, and bull cases with explicit assumptions about demand, margins, capital intensity, multiple, asset value, or cycle position. A target price without stated assumptions is not one.

**Buy Candidate** — the pipeline's terminal buy-side output: a pool name whose right-side volume/price signal fired on a given trading day, carrying the facts behind it (signal grade, entry stage vs. stage required, effective valuation tier, band position, over-extension). Governed by workflow §8–§11. It is **not** an instruction to buy; the pipeline emits no buy or sell recommendation, and position sizing is outside it.

**Pretrade Decision** *(retired v2.05)* — the former structured buy gate between a buy candidate and an actual position. The 15-item gate and its `approved`/`compliant`/`off_system`/`hold_off` verdicts were retired on 2026-08-03; `data/archive/pretrade_decisions_2026-08-03.csv` is a closed historical record. Retained here only so the term is recognizable in old decision-log rows and archived docs — **do not apply it.**

**Position Plan** — non-binding portfolio guidance downstream of both moat screening and valuation assessment. It belongs to a security, and is never evidence that the underlying company has a stronger moat.

## Market And Financial Data

**Market Data** — daily trading records (open, high, low, close, volume, turnover, trading status). Belongs to a security and trading date.

**Corporate Action** — an issuer event affecting ownership, cash flows, or historical price comparability: dividends, splits, bonus shares, rights issues. Affects how market data must be interpreted.

**Financial Report Data** — reported statements, key metrics, narrative disclosures, and their reporting periods. Belongs to a listed company and reporting period.

**Disclosure Timeline** — expected, preliminary, forecast, and official announcement dates for reporting events. The workflow's review triggers depend on distinguishing these from the reporting period itself.

## Key Relationships

- A listed company can have several securities. A **Universe** contains securities; a **Watchlist** contains listed companies.
- Every eligible company gets an **Attention Class**; only worth-attention companies then receive a **Quality Tier**.
- **Moat Screening** gates attention; **Valuation Assessment** gates price; **Position Plan** is downstream of both. None substitutes for another.
- An **Investment Strategy Tag** must be assigned before valuation, because it selects the method.
- In A-share operational files, `security_code` is the working anchor for company-level conclusions. Multi-security companies (AH duals, for example) keep the conclusion on the A-share code; cross-market reuse maps through the company analysis index rather than assuming one code per company.

## Retired Vocabulary

These terms appear in older documents under `docs/peer-group-calibration/` and in `docs/archive/moat-scoring-rubric.md`. They are no longer part of the operative A-share model — treat them as historical:

- **Two-Layer Company Review**, **Triage Review**, **Deep Company Review**, **Full-Coverage Screening Run**, **Dimensional Score**, **Special Dimension**, **Moat Score** — the score-driven two-layer review, de-scoped from A-shares by ADR-0006. `docs/archive/moat-scoring-rubric.md` served the Hong Kong and U.S. coverage scorers until those were retired in v2.00; nothing references it now. Do not confuse the old `Moat Score` with the tiering-v2 `quality_score`.
- **Final Screening Result**, **Watch Selection Route** — pointed at `a_share_final_screening_results.csv`, which no longer exists. Current structured sources of truth are `a_share_attention_triage.csv` and `a_share_watchlist_quality_tiers.csv`.
- **Cross-Market Calibration**, **Market-Staged Calibration** — belong to the Hong Kong/U.S. scoring path, not the A-share pipeline.
