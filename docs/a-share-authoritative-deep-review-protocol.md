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

1. **L1 - Core candidate**: reserve for companies that can anchor the watchlist against the strongest existing peers. The company must have a hard-to-replicate moat, leading industry position, strong long-term business quality, and a source-backed path to remain important across cycles.
2. **L2 - Quasi-core candidate**: use for high-quality companies with strong advantages, but with a material limitation such as cyclicality, valuation sensitivity, narrower market space, weaker proof of bottleneck status, governance risk, or weaker position versus L1 peers.
3. **L3 - Tactical candidate**: do not use as a generic middle bucket. The company must have at least one clear tactical reason for attention: a visible industry catalyst, right-side trigger candidate, cycle inflection, local bottleneck, differentiated technology, meaningful shareholder-return catalyst, or source-backed turnaround path. If the thesis is only "good company, possible growth, or possible rebound", downgrade to L4.
4. **L4 - Zero-position watch**: use as the conservative default for companies that are understandable and may deserve occasional review, but lack enough moat strength, catalyst clarity, peer differentiation, or evidence quality to occupy the first three tiers.
5. **L5 - Remove from watchlist**: use when the company is low-barrier, easily copied, comprehensively dominated by stronger peers, weak on cash-flow quality, mainly theme/cycle driven without durable advantage, or only attractive under too many assumptions.

Peer double-check must compare a company not only with weaker peers, but also with already assigned L1/L2/L3 anchors. A company should not enter L3 unless it would still deserve attention after being compared with the current L3 anchors.

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
