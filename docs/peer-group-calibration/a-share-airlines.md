# 1. A-Share Airlines Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `交通运输-航空机场-航空`.

The group mixes national passenger airlines, low-cost airlines, private full-service airlines, air cargo and logistics platforms, regional airlines, and general-aviation helicopter services. The review separates route and hub scarcity from true business-quality compounding.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have a clearly differentiated operating model, such as a low-cost airline cost structure, or integrated air-logistics capability tied to scarce hub resources.
2. Retain boundary cases when they have major-carrier hub and slot scarcity, dedicated air-cargo network assets, differentiated regional-airline positioning, or scarce general-aviation licenses and customer relationships.
3. Reject airlines when governance and balance-sheet history weaken the route network, or when a mid-sized full-service model lacks both a low-cost moat and major-carrier scarcity.
4. Airline route rights, slots, hubs, safety systems, and aircraft networks are real barriers, but airlines remain exposed to fuel, FX, recession, disease shocks, and high capital intensity. A watched airline should be treated as a cyclical scarcity asset, not a default compounder.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_airlines_peer_group_decisions.csv`.

Direct watch:

- 春秋航空
- 东航物流

Boundary watch after analyst judgment:

- 南方航空
- 中国国航
- 中国东航
- 国货航
- 华夏航空
- 中信海直

The remaining companies are rejected for now because bankruptcy and governance history weakens the scarcity thesis, or because the company lacks both a low-cost model and major-carrier network scarcity.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. Each decision row also adds the relevant exchange disclosure landing page and official company website when available. Later deep-company reviews should use annual reports, fleet and route disclosures, slot and hub evidence, passenger yield and load-factor history, cargo tonnage data, unit-cost evidence, balance-sheet and lease disclosures, safety and license records, and reputable institutional research.
