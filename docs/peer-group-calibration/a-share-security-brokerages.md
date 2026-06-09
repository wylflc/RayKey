# 1. A-Share Security Brokerages Peer-Group Review
## 1.1 Purpose
This note records the company-by-company review for `金融-非银行金融-证券`.

This group contains national full-service securities firms, investment-bank specialists, wealth-management platforms, bank/SOE affiliated brokers, regional brokers, and mixed holding companies. Brokerage earnings are cyclical, so the review retains only firms whose scale, institutional franchise, technology, international footprint, or client ecosystem is meaningfully harder to copy than a regional license.
## 1.2 Retention Standard
1. Directly retain national leaders with full-service institutional, wealth, investment-bank, derivatives, international, and balance-sheet capability.
2. Boundary-retain large or differentiated brokers with strong regional ecosystems, technology-led wealth platforms, or distinctive investment-bank/asset-management franchises.
3. Reject regional, small, mixed, or holding-company brokers when a stronger retained peer already covers the industry beta and the company lacks independent franchise superiority.

## 1.3 Decisions
The structured decision file is `data/processed/a_share_security_brokerages_peer_group_decisions.csv`.

Direct watch:
- 中信证券
- 国泰海通
- 中金公司
- 华泰证券

Boundary watch after analyst judgment:
- 广发证券
- 招商证券
- 中信建投
- 中国银河
- 国信证券
- 申万宏源
- 东方证券

The remaining companies are rejected for now because they lack the specific durable advantage required for this peer group, or because stronger retained peers already cover the same investable thesis.

## 1.4 Sources
This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. Each decision row also includes the available exchange disclosure landing page and official company website when available. Later deep-company reviews should replace first-pass evidence with annual reports, segment disclosures, customer or regulatory qualification evidence, normalized margin data, and reputable institutional research.
