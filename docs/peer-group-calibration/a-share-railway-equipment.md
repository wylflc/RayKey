# 1. A-Share Railway Equipment Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `交运设备-铁路设备-铁路专用设备及器材`.

The group mixes railway engineering and maintenance equipment, high-speed rail fasteners and track materials, high-reliability connectors, rail signal and safety systems, rail monitoring and inspection equipment, rail vehicle components, maintenance-platform stories, mature rail axle manufacturers, and ST rail-equipment cases. The review separates safety-critical qualification moats from ordinary rail-component supply.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have national railway qualification, safety-critical track-material applications, high-reliability connector platforms, or embedded signal/safety-control systems.
2. Retain boundary cases when they have narrower but real railway fastener components, signal monitoring, inspection equipment, or rail-safety niches.
3. Reject ordinary rail vehicle interior/HVAC components, mature axle manufacturers, project-heavy maintenance platforms with weak operating quality, and ST rail-equipment companies.
4. A watched railway-equipment company must show certification, line-use history, customer replacement cost, safety-critical product role, or high-reliability cross-market extension.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_railway_equipment_peer_group_decisions.csv`.

Direct watch:

- 金鹰重工
- 铁科轨道
- 永贵电器
- 科安达

Boundary watch after analyst judgment:

- 祥和实业
- 铁大科技
- 日月明
- 交大铁发

The remaining companies are rejected for now because they are ordinary rail vehicle component suppliers, weaker maintenance-platform stories, mature axle manufacturers, or ST rail-equipment companies where governance/operating risk overwhelms the technical case.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, CRCC/CRRC and railway-customer qualification records, product certification disclosures, line-use references, safety-certification evidence, revenue by railway product, and reputable institutional research where needed.
