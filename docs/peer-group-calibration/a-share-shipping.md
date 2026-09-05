# 1. A-Share Shipping Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `交通运输-港口航运-航运`.

The group mixes global liner platforms, diversified shipping platforms, energy-shipping leaders, special-cargo shipping, product tanker operators, regional container lines, domestic container logistics, port-backed feeder operators, route-scarcity ferry operators, chemical and dangerous-goods shipping companies, shipping finance/leasing profiles, dry-bulk fleets, forwarding services, and unclear transformed shipping classifications. The review separates network and qualification moats from ordinary vessel capacity.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have global route networks, terminal integration, diversified fleet scale, energy-transport qualifications, long-term customer contracts, or differentiated special-cargo ship types and operating know-how.
2. Retain boundary cases when they have narrower but visible product-tanker specialization, regional liner networks, domestic container routing density, port-backed feeder linkage, route-scarcity ferry assets, or chemical and dangerous-goods shipping qualifications.
3. Reject ordinary dry-bulk shipping, smaller ferry duplicates, regional bulk/coal shipping, shipping finance/leasing without superior platform economics, small forwarding services, and unclear transformed classifications.
4. Shipping cyclicality is explicitly penalized. A watched company must show route network, fleet specialization, safety qualification, customer contract, port linkage, or route scarcity beyond generic vessel ownership.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_shipping_peer_group_decisions.csv`.

Direct watch:

- 招商轮船
- 中远海控
- 中远海能
- 中远海特

Boundary watch after analyst judgment:

- 招商南油
- 锦江航运
- 中谷物流
- 宁波远洋
- 海峡股份
- 兴通股份
- 盛航股份

The remaining companies are rejected for now because they are shipping finance/leasing profiles, smaller ferry duplicates, ordinary dry-bulk or regional bulk/coal operators, small forwarding services, unclear transformed classifications, or legacy inland shipping capacity.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, fleet composition, route network data, long-term contract disclosures, safety and chemical-shipping qualification records, utilization and freight-rate sensitivity, orderbook exposure, alliance data, and reputable institutional research where needed.
