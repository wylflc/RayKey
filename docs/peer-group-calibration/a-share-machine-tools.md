# 1. A-Share Machine Tools Peer-Group Review

## 1.1 Purpose

This pass reviews industrial mother machines, CNC systems, high-end grinders, spindles, machine-tool platforms, and adjacent precision equipment.

This note records the company-by-company review for `机械设备-通用设备-机床设备`.

## 1.2 Retention Standard

1. Directly retain strategic industrial-mother-machine and CNC-control platforms with domestic substitution, high-end process, or core-control-system capability.
2. Boundary-retain focused component, precision grinding, or machine-tool platforms when they have clear product specialization and customer validation.
3. Reject generic machine-tool assemblers or weaker copies when a stronger retained platform covers the same equipment layer.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_machine_tools_peer_group_decisions.csv`.

Direct watch:

- 秦川机床
- 华中数控
- 科德数控

Boundary watch after analyst judgment:

- 昊志机电
- 华辰装备
- 国盛智科
- 沈阳机床
- 海天精工
- 纽威数控
- 纳科诺尔

The remaining companies are rejected for now because they lack the specific durable advantage required for this peer group, are weaker than retained peers, or are better described as low-barrier capacity/project/cycle exposure.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. Each decision row includes the available exchange disclosure landing page and official company website when available. Later deep-company reviews should replace first-pass evidence with annual reports, segment disclosures, customer or regulatory qualification evidence, normalized margin data, and reputable institutional research.
