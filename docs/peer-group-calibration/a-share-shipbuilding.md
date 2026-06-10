# 1. A-Share Shipbuilding Peer-Group Review

## 1.1 Purpose

This group includes core shipbuilding platforms, marine power systems, ship defense platforms, mooring chain niches, small boat builders, ship design services, ship electrical suppliers, and unrelated reclassified cases.

## 1.2 Retention Standard

1. Retain direct-watch companies when they are core shipbuilding or marine-power platforms with state-level program participation, yard scale, and supply-chain orchestration capability.
2. Retain boundary cases when a niche such as offshore mooring chain or defense shipbuilding has global qualification and difficult manufacturing validation.
3. Reject small boats, project design, ship electrical suppliers, unrelated reclassified businesses, or weak transition cases when they lack platform control or a hard-to-replace niche.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_shipbuilding_peer_group_decisions.csv`.

Direct watch:

- 中国动力
- 中国船舶

Boundary watch after analyst judgment:

- 亚星锚链
- 中船防务

4 companies are rejected for now. Rejections are company-specific and recorded in the CSV; common reasons include weaker duplicate capability, commodity or project-cycle exposure, low-barrier products, ST/restructuring risk, or lack of platform control versus retained peers.

## 1.4 Sources

This first-pass peer-group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv` as discovery metadata. Each decision row records official exchange disclosure landing pages and official company websites when available. Aggregator company introductions are not treated as decisive evidence. Later deep-company reviews should use annual reports, exchange announcements, official investor-relations materials, product certifications, customer qualification evidence, market-share evidence, segment margins, cost-curve evidence, and reputable institutional research where needed.
