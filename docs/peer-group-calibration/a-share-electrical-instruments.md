# 1. A-Share Electrical Instruments Peer-Group Review
## 1.1 Purpose
This note records the company-by-company review for `电气设备-输变电设备-电气仪表`.

This group contains smart meters, electricity information-collection systems, power-quality monitoring, user-side energy management, microgrid software, field communication, and generic industrial instruments. The review separates grid-qualified energy IoT and metering platforms from ordinary instruments and control valves.
## 1.2 Retention Standard
1. Directly retain companies with grid metering scale, user-side energy data, smart distribution products, or energy IoT platforms that benefit from power-system digitalization.
2. Boundary-retain narrower power-quality, microgrid, field-network, or storage/smart-grid companies when customer qualification and product platform evidence are visible.
3. Reject generic temperature, industrial-control, flow-control, and ST cases without durable grid qualification or energy-data workflow control.

## 1.3 Decisions
The structured decision file is `data/processed/a_share_electrical_instruments_peer_group_decisions.csv`.

Direct watch:
- 炬华科技
- 林洋能源
- 三星电气

Boundary watch after analyst judgment:
- 新联电子
- 灿能电力
- 安科瑞
- 科陆电子
- 友讯达

The remaining companies are rejected for now because they lack the specific durable advantage required for this peer group, or because stronger retained peers already cover the same investable thesis.

## 1.4 Sources
This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. Each decision row also includes the available exchange disclosure landing page and official company website when available. Later deep-company reviews should replace first-pass evidence with annual reports, segment disclosures, customer or regulatory qualification evidence, normalized margin data, and reputable institutional research.
