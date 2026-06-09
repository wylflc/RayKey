# 1. A-Share Railway Transport Peer-Group Review
## 1.1 Purpose
This note records the company-by-company review for `交通运输-公路铁路-铁路运输`.

This group contains high-speed passenger rail, coal freight rail, regional rail operators, railway container logistics, special-cargo rail logistics, and mixed regional logistics assets. The review separates irreplaceable rail corridors and specialized rail logistics from ordinary local logistics operations.
## 1.2 Retention Standard
1. Directly retain irreplaceable high-density corridors with route monopoly, asset scarcity, and long-duration traffic demand.
2. Boundary-retain coal/freight rail and railway logistics companies when the asset or operating license is scarce, while discounting commodity or regional-cycle exposure.
3. Reject smaller mixed logistics companies when route control and network economics are not strong enough.

## 1.3 Decisions
The structured decision file is `data/processed/a_share_railway_transport_peer_group_decisions.csv`.

Direct watch:
- 京沪高铁

Boundary watch after analyst judgment:
- 大秦铁路
- 广深铁路
- 铁龙物流
- 广汇物流
- 中铁特货

The remaining companies are rejected for now because they lack the specific durable advantage required for this peer group, or because stronger retained peers already cover the same investable thesis.

## 1.4 Sources
This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. Each decision row also includes the available exchange disclosure landing page and official company website when available. Later deep-company reviews should replace first-pass evidence with annual reports, segment disclosures, customer or regulatory qualification evidence, normalized margin data, and reputable institutional research.
