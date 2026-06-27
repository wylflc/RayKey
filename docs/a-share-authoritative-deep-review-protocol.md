# 1. A-Share Authoritative Deep Review Protocol

## 1.1 Purpose

`data/processed/a_share_watchlist_quality_tiers.csv` is only a preliminary queue-prioritization file. It is not a final stock-analysis result and must not be treated as evidence that each company has been reviewed deeply.

The authoritative A-share review must be completed company by company. A company can receive a final quality tier only after its review cites and uses authoritative sources, applies the strategy-specific analysis method, and compares the company against relevant peers.

## 1.2 Required Sources

Each completed company review must use, at minimum:

1. The latest annual report.
2. The latest interim report, quarterly report, or equivalent current official disclosure.
3. Relevant exchange announcements, regulator disclosures, or official investor-relations materials when they affect the thesis.
4. At least one reputable institution report or clearly attributed professional research report when available.

Aggregator profile pages, F10-style company introductions, unsourced media summaries, and social-media claims may be used only as discovery hints. They are not sufficient analytical evidence.

If a reputable research report is not publicly available, the review must explicitly record that limitation instead of silently omitting it.

## 1.3 Output Files

- `data/processed/a_share_final_watchlist.csv`: current A-share watchlist extracted from the final screening result.
- `data/processed/a_share_watchlist_quality_tiers.csv`: preliminary queue tiering only. It is not stock-analysis-compliant final research.
- `data/interim/a_share_authoritative_deep_review_queue.csv`: pending per-company work queue for the authoritative deep review.

## 1.4 Completion Standard

A row in `data/interim/a_share_authoritative_deep_review_queue.csv` may move from `pending_authoritative_deep_review` to a final reviewed status only after the analyst records:

1. Source URLs for the annual report, current official disclosure, official announcement or IR material when relevant, and reputable research report when available.
2. Final primary strategy tag: A DCF / cash-flow compounder, B cigar-butt undervaluation, C GARP growth, D supply-chain breakout, E fallen champion, F monopoly resource, or G shareholder-return undervaluation.
3. Business-quality conclusion before valuation: moat, capital-replicability resistance, technical or process barrier, market position, operating quality, governance and red flags.
4. Peer double-check: whether the company deserves its tier compared with already assigned peers in the same or adjacent strategy group.
5. Strategy-specific valuation relevance note: the valuation method to use later and why one-size-fits-all PE/PB/PEG is insufficient or sufficient.
6. Bear, base, and bull case summaries.
7. Invalidation conditions and monitoring metrics.

## 1.5 Review Discipline

The review must separate three decisions:

1. Whether the listed company deserves ongoing attention based on business quality.
2. Whether the security is currently undervalued or attractive.
3. Whether portfolio position size is appropriate.

A cheap price cannot upgrade a weak business into a high-quality watchlist candidate. An expensive price cannot remove a genuinely high-quality business from the watchlist; it only affects the current action.

## 1.6 Tier Calibration

Final tiers should normally form a pyramid after enough companies have been reviewed. The upper tiers are scarce attention slots, not descriptions of whether a company is merely good.

Use the following stricter calibration from batch 009 onward:

1. **L1 - Core candidate**: reserve for companies that can anchor the watchlist against the strongest existing peers. The company must have a hard-to-replicate moat, leading industry position, strong long-term business quality, and a source-backed path to remain important across cycles. L1 is market-cap neutral: current market value, index weight, or trading liquidity cannot be used as a required condition for L1.
2. **L2 - Quasi-core candidate**: use for high-quality companies with strong advantages, but with a material limitation such as cyclicality, narrower market space, weaker proof of bottleneck status, governance risk, weaker position versus L1 peers, or insufficient evidence that the advantage can remain durable across multiple product or industry cycles. Current valuation sensitivity belongs in a later valuation assessment and must not by itself downgrade a business-quality tier.
3. **L3 - Tactical candidate**: do not use as a generic middle bucket. The company must have at least one clear tactical reason for attention: a visible industry catalyst, right-side trigger candidate, cycle inflection, local bottleneck, differentiated technology, meaningful shareholder-return catalyst, or source-backed turnaround path. If the thesis is only "good company, possible growth, or possible rebound", downgrade to L4.
4. **L4 - Zero-position watch**: use as the conservative default for companies that are understandable and may deserve occasional review, but lack enough moat strength, catalyst clarity, peer differentiation, or evidence quality to occupy the first three tiers.
5. **L5 - Remove from watchlist**: use when the company is low-barrier, easily copied, comprehensively dominated by stronger peers, weak on cash-flow quality, mainly theme/cycle driven without durable advantage, or only attractive under too many assumptions. Here "remove from watchlist" means demote the company out of worth-attention back into boundary-pending for possible future re-review; it is not the same as the permanent garbage exclusion, which is decided only in the first-round triage.

Peer double-check must compare a company not only with weaker peers, but also with already assigned L1/L2/L3 anchors. A company should not enter L3 unless it would still deserve attention after being compared with the current L3 anchors.

Use the following L1 subtypes to avoid mixing unrelated reasons:

1. **L1 durable moat / cash-flow anchor**: a company can be L1 even when industry growth is slow if its moat is extremely hard to replicate, cash conversion and margin quality are exceptional, and the listed company is likely to remain a category anchor for many years. Weak industry growth, demographic pressure, or mature demand should be recorded in valuation, expected-return, and position-sizing notes; these factors should not downgrade an ultra-durable moat from L1 by themselves.
2. **L1 strategic bottleneck / platform anchor**: a company can be L1 when it controls a critical technology, system platform, resource, standard, customer certification layer, or supply-chain bottleneck that is both material to downstream demand and difficult for well-funded entrants to replace.
3. **L1 small-cap exception**: a smaller listed company can be L1 if authoritative sources show a genuinely irreplaceable niche, global or national leading position, high customer switching cost, and a plausible path for the advantage to remain material. Small size raises the evidence burden and may reduce eventual position size, but it does not cap the business-quality tier.

For medical-device companies, separate a broad platform moat from a specialized clinical moat:

1. A broad platform can be L1 only when product breadth is reinforced by shared hospital channels, installed base, service network, quality systems, global registration capability, R&D reuse, and cash conversion. Merely having many product lines is not enough.
2. Specialized high-barrier companies in electrophysiology, vascular intervention, high-end imaging, endoscopy, implants, consumables, or biomaterials normally start at L2 unless they can prove a category-defining position large enough to anchor the watchlist on their own.
3. Acquisition or control by an L1 platform is positive validation of the target's technology and clinical value, but it does not automatically upgrade the target to L1. The target still needs standalone evidence of durable market leadership, cash-flow quality, and multi-cycle relevance; expected platform synergies should be recorded as an upgrade trigger, not assumed as already proven.
4. A platform company should be downgraded if product-line breadth begins to dilute ROIC, weaken cash conversion, create integration drag, hide weak franchises behind strong ones, or if key product lines lose share against focused competitors.

For AI and semiconductor supply-chain names, do not equate short-term profit explosion with a stronger moat. Optical module, PCB, packaging, semiconductor equipment, EDA, and interface-chip companies must be compared on both:

1. **Current bottleneck intensity**: whether downstream demand, customer certification, capacity, yield, and delivery constraints are causing near-term profit capture.
2. **Durable technical or ecosystem moat**: whether patents, standards participation, design complexity, process know-how, platform software, customer lock-in, and multi-generation product roadmaps can protect the company after the current demand wave normalizes.

If a company has very strong current bottleneck intensity but weaker multi-cycle technical or ecosystem durability, it may still be L1 as a strategic bottleneck anchor, but its notes must explicitly label product-cycle, customer-concentration, and pricing risks. Conversely, a company with deeper technical or ecosystem moat should not be kept below a current-cycle winner solely because its near-term earnings beta is lower.

## 1.7 Batch Size

Deep reviews should be performed in small batches. The queue uses 20-company batches only to make progress resumable. The batch label is not analytical evidence and must not be used to infer quality.

## 1.8 Prohibited Shortcuts

The following are not acceptable as final analysis:

1. Assigning tiers from industry keywords, peer-group labels, or previous numeric scores alone.
2. Treating Eastmoney-style F10 introductions as sufficient evidence.
3. Inferring moat from current profitability alone.
4. Ignoring the capital-replicability test.
5. Marking a company complete without bear/base/bull cases.
6. Letting current valuation decide watchlist eligibility.
