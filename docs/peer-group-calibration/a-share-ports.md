# 1. A-Share Ports Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `交通运输-港口航运-港口`.

The group mixes national and global port platforms, world-scale deepwater gateways, international container hubs, regional comprehensive ports, bulk ports, emerging strategic gateway ports, single-port container assets, inland ports, and mixed local logistics or utility profiles. The review separates irreplaceable port location and cargo control from ordinary local port stability.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have national/global port-platform capability, world-scale deepwater gateway assets, international shipping-center status, route density, cargo diversity, and durable hinterland control.
2. Retain boundary cases when they have efficient bulk-port economics, major regional gateway position, emerging policy-corridor growth, high-quality single-port container assets, or strong regional comprehensive-port role.
3. Reject single-cargo coal ports, weaker regional port platforms, smaller coastal peers covered by stronger retained companies, small inland ports, mixed local logistics/utility profiles, and ports whose strategic location has not translated into durable economics.
4. Port natural monopoly is not enough. A watched company must show irreplaceable shoreline, route network, cargo base, hinterland economics, throughput resilience, pricing/fee discipline, or platform expansion capability.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_ports_peer_group_decisions.csv`.

Direct watch:

- 招商港口
- 宁波港
- 上港集团
- 青岛港

Boundary watch after analyst judgment:

- 唐山港
- 天津港
- 北部湾港
- 盐 田 港
- 广州港

The remaining companies are rejected for now because they are single-cargo coal ports, weaker regional platforms, smaller coastal peers, small inland ports, mixed port/logistics/utility profiles, or ports whose strategic location has not produced strong enough economics.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, throughput by cargo type, tariff and fee disclosures, hinterland and route data, capex plans, port integration disclosures, debt and dividend records, and reputable institutional research where needed.
