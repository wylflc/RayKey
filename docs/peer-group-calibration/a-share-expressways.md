# 1. A-Share Expressways Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `交通运输-公路铁路-高速公路`.

The group mixes national toll-road platforms, high-quality coastal and economic-corridor assets, strong provincial expressway platforms, lower-quality regional concessions, bridge assets, mixed real-estate/tourism/investment portfolios, and ordinary local toll concessions. The review separates route quality and platform scale from generic toll-license value.

## 1.2 Retention Standard

1. Retain direct-watch companies when they own national platform scale, high-quality economic-corridor assets, strong regional traffic density, and durable toll cash flow.
2. Retain boundary cases when they have meaningful provincial or regional toll-road assets, but lower scale, lower region quality, or more mixed reinvestment risk than direct leaders.
3. Reject ordinary regional expressway companies, small bridge/road assets, weaker provincial routes, mixed real-estate/tourism/investment portfolios, and operators whose moat is only a local toll concession.
4. Stable cash flow is necessary but not sufficient; the watchlist should focus on route quality, traffic density, concession durability, and reinvestment discipline.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_expressway_peer_group_decisions.csv`.

Direct watch:

- 招商公路
- 粤高速Ａ
- 山东高速
- 宁沪高速

Boundary watch after analyst judgment:

- 皖通高速
- 福建高速
- 赣粤高速
- 深高速
- 四川成渝

The remaining companies are rejected for now because they are ordinary regional toll-road operators, smaller bridge/road assets, weaker provincial routes, mixed real-estate/tourism/investment portfolios, or operators whose moat is only a local concession without enough route quality, traffic density, platform advantage, or reinvestment discipline.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with direct annual reports, concession-period disclosures, traffic-volume data, toll-rate disclosures, debt and capex plans, dividend policies, and reputable institutional research where needed.
