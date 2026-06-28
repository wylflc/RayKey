# 1. A-Share Decoration-Construction Peer-Group Review

## 1.1 Purpose

This group reviews interior decoration, curtain wall, building envelope, and decorative-material companies. The industry is exposed to real-estate cycles and project bidding; most advantages are execution-heavy rather than durable moats.

## 1.2 Retention Standard

1. Retain only when a company owns a hard specialty material, globally validated system, or platform economics beyond construction contracting.
2. Reject ordinary decoration contractors, interior designers, and regional construction-service companies when funded entrants can hire teams and bid projects.
3. Do not retain companies merely because historical project scale or current margins look acceptable.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_decoration_construction_peer_group_decisions.csv`.

Direct watch:

- None

Boundary watch after analyst judgment:

- None

27 companies are rejected for now out of 27 reviewed rows. Rejected companies lack enough company-specific moat under this group's retention standard, even when local scale or current profitability looked acceptable.

## 1.4 Sources

This first-pass peer-group review uses the local full-coverage score fields as background metadata and records official exchange disclosure landing pages in each decision row. Aggregator company introductions are not treated as decisive evidence. Later deep-company reviews should use annual reports, exchange announcements, official investor-relations materials, customer qualification evidence, segment margins, market-share evidence, and reputable institutional research where needed.

## 1.5 New-Standard Recalibration (ADR-0006)

Re-applying the round-1 standard (operation-workflow §5.4) confirms 建筑装饰 as a **structurally hopeless industry**: low entry barrier (funded entrants can hire teams, obtain qualifications, and bid), an advance-payment / receivables / real-estate-dependent model with structurally poor cash flow and cyclical bad-debt blowups (the property crash drove a large share into *ST), and execution-heavy advantages that are not durable moats. About half the listed names are now *ST/ST. This is the anchor case for `garbage(structural_industry)`.

Calibrated round-1 result (written to `data/processed/a_share_attention_triage.csv`):

| Class | Companies | Basis |
| --- | --- | --- |
| garbage / structural_industry (14) | 金螳螂, 亚厦股份, 广田集团, 郑中设计, 名雕股份, 维业股份, 全筑股份, *ST宝鹰, *ST瑞和, *ST东易, ST中装, *ST美芝, ST名家汇, *ST利达 | Structurally broken industry model; the verdict applies even to the relative leader 金螳螂 — high-end fit-out brand/qualifications did not protect returns (a value trap). Verify any confirmed fraud → governance_fraud. |
| boundary_pending (1) | 江河集团 | High-end curtain-wall system (more technical/qualification barrier than ordinary interior decoration) + medical diversification — a structurally different, higher-barrier sub-segment. Reversible. |

Generalizable rule distilled into operation-workflow §5.4.5 (rule 8): structural_industry garbage applies at the right sub-industry granularity and reaches the relative leader (execution / brand / historical scale are not durable moats in a broken model); only a genuinely higher-barrier sub-segment is carved out to boundary.
