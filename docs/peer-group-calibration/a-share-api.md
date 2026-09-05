# 1. A-Share API And Chemical Raw Drugs Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `医药生物-化学制药-化学原料药`.

The group includes API-CDMO platforms, regulated API manufacturers, sterile injectable platforms, radiopharmaceuticals, vitamins, excipients, contrast-agent APIs, and commodity intermediates. The review focuses on whether a company has durable process development, quality-system, regulatory, customer-validation, cost, or scarce-license advantages that cannot be replicated by capital alone.

## 1.2 Retention Standard

1. Retain API companies when process development, quality systems, regulatory filings, customer validation, cost position, or scarce licenses create durable barriers beyond commodity chemical capacity.
2. Retain boundary cases when a company owns a distinct regulated-product, cost/process, excipient, contrast-agent, or specialty-ingredient niche that is not fully covered by stronger retained peers.
3. Reject commodity, cyclical, weakly differentiated, or duplicate API/intermediate producers when their advantage can be competed away by capacity expansion or larger integrated manufacturers.
4. Current profit volatility is not the main rejection reason; weak differentiation and easy replication are.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_api_peer_group_decisions.csv`.

Direct watch:

- 普洛药业
- 华海药业
- 健友股份
- 东诚药业

Boundary watch after analyst judgment:

- 花园生物
- 新诺威
- 海正药业
- 浙江医药
- 国邦医药
- 天宇股份
- 山河药辅
- 博瑞医药
- 司太立

The remaining reviewed companies are rejected for now because their businesses are more commodity-like, cyclical, duplicative, or weaker in regulated-product and process differentiation than retained API, CDMO, excipient, contrast-agent, or radiopharmaceutical platforms.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. These rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with direct annual reports, exchange announcements, product approvals, GMP/FDA/EMA inspection or registration evidence, and reputable institutional research where needed.
