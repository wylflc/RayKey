# 1. A-Share Telecom Operators Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `信息技术-通信运营-通信运营`.

The group mixes national telecom operators, satellite operators, data-center and computing-infrastructure platforms, State Grid information-communication platforms, cloud communication providers, video-conferencing and AI interaction vendors, and telecom-adjacent smart-home service companies. The review separates scarce infrastructure control from ordinary communication services.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have spectrum, nationwide network assets, customer scale, fixed-line/mobile/cloud integration, enterprise customers, and computing or digital-infrastructure capability.
2. Retain boundary cases when they have national telecom scarcity but weaker relative economics, autonomous satellite resources, high-grade data-center parks, or State Grid information-communication customer access.
3. Reject video-conferencing, cloud communication, smart-home, and telecom-adjacent service companies when they lack infrastructure, spectrum, customer lock-in, or workflow control.
4. A watched telecom company must control scarce network, spectrum, satellite, power/data-center, or grid-customer infrastructure that capital alone cannot quickly reproduce.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_telecom_operators_peer_group_decisions.csv`.

Direct watch:

- 中国移动
- 中国电信

Boundary watch after analyst judgment:

- 中国联通
- 中国卫通
- 润泽科技
- 国网信通

The remaining companies are rejected for now because they are smaller cloud-communication, video-interaction, or telecom-adjacent service providers without operator-level infrastructure scarcity.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. Each decision row also adds the relevant exchange disclosure landing page and official company website when available. Later deep-company reviews should use annual reports, subscriber and ARPU data, capex and spectrum disclosures, cloud and IDC revenue data, data-center utilization and power evidence, satellite capacity and orbital-resource disclosures, State Grid project disclosures, and reputable institutional research.
