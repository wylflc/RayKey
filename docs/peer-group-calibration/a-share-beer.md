# 1. A-Share Beer Peer-Group Review
## 1.1 Purpose
This note records the company-by-company review for `食品饮料-饮料-啤酒`.

This group contains national beer brands, regional beer companies, ST local beer assets, and a malt supplier. Beer has stronger channel/brand concentration than many food categories but lower long-term volume growth, so the review keeps national and differentiated category leaders only.
## 1.2 Retention Standard
1. Directly retain national or internationally backed beer leaders with brand, channel, premiumization and scale advantages.
2. Boundary-retain strong regional beer brands or upstream malt scale leaders when they have category leadership or supply-chain importance.
3. Reject local or ST beer assets where brand and channel are too narrow and long-term volume growth is weak.

## 1.3 Decisions
The structured decision file is `data/processed/a_share_beer_peer_group_decisions.csv`.

Direct watch:
- 青岛啤酒
- 重庆啤酒

Boundary watch after analyst judgment:
- 珠江啤酒
- 永顺泰
- 燕京啤酒

The remaining companies are rejected for now because they lack the specific durable advantage required for this peer group, or because stronger retained peers already cover the same investable thesis.

## 1.4 Sources
This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. Each decision row also includes the available exchange disclosure landing page and official company website when available. Later deep-company reviews should replace first-pass evidence with annual reports, segment disclosures, customer or regulatory qualification evidence, normalized margin data, and reputable institutional research.
