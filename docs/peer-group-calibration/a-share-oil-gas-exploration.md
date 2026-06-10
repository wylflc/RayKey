# 1. A-Share Oil And Gas Exploration Peer-Group Review

## 1.1 Purpose

This group compares national oil and gas resource owners, offshore oil producers, coalbed-methane resource operators, oilfield-service subsidiaries, smaller oil-and-gas producers, and ST energy cases.

## 1.2 Retention Standard

1. Retain direct-watch companies when reserve ownership, national license position, cost curve, infrastructure, and upstream operating capability create a resource moat that capital alone cannot replicate.
2. Retain boundary resource cases when local resource rights or infrastructure create a differentiated position but scale and diversification are lower than the national leaders.
3. Reject oilfield services, smaller producers, and ST cases when they lack reserve ownership, low-cost resource advantage, or a durable integrated infrastructure moat.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_oil_gas_exploration_peer_group_decisions.csv`.

Direct watch:

- 中国海油
- 中国石油

Boundary watch after analyst judgment:

- 蓝焰控股

5 companies are rejected for now. Rejections are company-specific and recorded in the CSV; common reasons include weaker duplicate capability, commodity or project-cycle exposure, low-barrier products, ST/restructuring risk, or lack of platform control versus retained peers.

## 1.4 Sources

This first-pass peer-group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv` as discovery metadata. Each decision row records official exchange disclosure landing pages and official company websites when available. Aggregator company introductions are not treated as decisive evidence. Later deep-company reviews should use annual reports, exchange announcements, official investor-relations materials, product certifications, customer qualification evidence, market-share evidence, segment margins, cost-curve evidence, and reputable institutional research where needed.
