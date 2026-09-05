# 1. A-Share Electrical Automation Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `电气设备-输变电设备-电气自控设备`.

The group mixes grid automation, relay protection, dispatch and distribution automation, UHV/DC and high-voltage equipment, global relays, industrial control, renewable power conversion, domain-specific automation, distribution switchgear, charging piles, project-heavy power IT, narrow control niches, and weak legacy electrical-equipment companies. The review separates embedded grid and industrial-control platforms from ordinary electrical equipment.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have core smart-grid automation, relay protection, dispatch automation, UHV/DC equipment, high-voltage equipment, global relay leadership, or strong grid-customer switching costs.
2. Retain boundary cases when they have second-tier but real power-automation installed bases, hydro/energy automation know-how, renewable power-conversion products, domestic PLC/industrial-control capability, or non-trivial industrial automation integration.
3. Reject ordinary distribution equipment, switchgear, charging-pile mixes, project-heavy power IT, narrow controller niches, weaker duplicate automation peers, and weak legacy electrical-equipment companies.
4. A watched company must show grid qualification, installed base, system switching cost, product reliability, UHV/DC engineering references, industrial-control product stack, or power-electronics product leadership. Tender participation alone is not enough.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_electrical_automation_peer_group_decisions.csv`.

Direct watch:

- 国电南瑞
- 东方电子
- 思源电气
- 许继电气
- 宏发股份
- 四方股份

Boundary watch after analyst judgment:

- 国电南自
- 华自科技
- 禾望电气
- 信捷电气
- 海得控制

The remaining companies are rejected for now because they are ordinary distribution-equipment companies, switchgear or charging-pile mixes, smaller drive/controller peers, project-heavy power IT or automation integrators, narrow control niches, weak legacy electrical-equipment companies, or companies whose governance/operating quality undermines the technical case.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, State Grid and Southern Grid tender disclosures, product certification records, installed-base evidence, UHV/DC project references, relay and protection product data, industrial-control product-line data, segment margins, and reputable institutional research where needed.
