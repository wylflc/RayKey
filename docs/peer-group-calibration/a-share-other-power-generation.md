# 1. A-Share Other Power Generation Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `公用事业-电力-其他发电`.

The group mixes nuclear power, grid technology services, regional coal-power platforms, provincial energy platforms, local heating utilities, provincial renewable operators, landfill-gas power, energy-finance holding companies, and ST transition cases. The review separates scarce regulated assets and grid technology capability from ordinary power capacity.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have scarce nuclear licenses, nuclear operating history, or utility-affiliated grid technology and smart-equipment capability.
2. Retain boundary cases when they have load-center regional scarcity, provincial energy-platform status, specialist wind-operation history, or regional integrated utility franchise characteristics.
3. Reject energy-finance holding profiles, ordinary local heat-power utilities, small renewable operators, niche waste-gas power operators, and ST transition stories without a scarce asset or technology.
4. Stable utility cash flow is not enough. A watched company must show that capital alone cannot quickly replicate its license, grid/customer access, region, dispatch position, resource control, or technical validation.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_other_power_generation_peer_group_decisions.csv`.

Direct watch:

- 南网科技
- 中国广核

Boundary watch after analyst judgment:

- 京能电力
- 江苏国信
- 中闽能源
- 天富能源

The remaining companies are rejected for now because they are energy-finance holding companies, ordinary local utility platforms, small renewable operators, landfill-gas power operators with limited scale, or ST transition cases without a verified durable company-level moat.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. Each decision row also adds the relevant exchange disclosure landing page and official company website when available. Later deep-company reviews should use annual reports, installed-capacity disclosures, nuclear license and utilization data, tariff and power-price disclosures, fuel-cost evidence, regional dispatch evidence, utility tender or project evidence, and reputable institutional research.
