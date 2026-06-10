# 1. A-Share Space Equipment Peer-Group Review

## 1.1 Purpose

This group covers satellite platforms, aerospace electronics, aero-engine platforms and parts, UAV systems, metamaterials, aerospace materials, time-frequency equipment, BeiDou/inertial-navigation suppliers, radar/microwave suppliers, and weaker ST or project-based defense electronics cases.

## 1.2 Retention Standard

1. Retain direct-watch companies when they control a scarce aerospace platform, aero-engine platform, satellite platform, core aerospace electronics system, or clearly differentiated metamaterial/aerospace-technology platform.
2. Retain boundary cases when qualification-heavy aerospace materials, UAV systems, time-frequency electronics, BeiDou/inertial-navigation products, rocket-related products, or microwave/composite subsystems have a hard-to-replace program role but less platform control.
3. Reject broad defense-electronics or ST cases when stronger retained peers cover the same thesis and the company does not show a unique system role.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_space_equipment_peer_group_decisions.csv`.

Direct watch:

- 光启技术
- 航天电子
- 中国卫星
- 航发动力

Boundary watch after analyst judgment:

- 振芯科技
- 航材股份
- 航发科技
- 中无人机
- 航天环宇
- 新余国科
- 天奥电子
- 中天火箭
- 星网宇达

3 companies are rejected for now. Rejections are company-specific and recorded in the CSV; common reasons include weaker duplicate capability, commodity or project-cycle exposure, low-barrier products, ST/restructuring risk, or lack of platform control versus retained peers.

## 1.4 Sources

This first-pass peer-group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv` as discovery metadata. Each decision row records official exchange disclosure landing pages and official company websites when available. Aggregator company introductions are not treated as decisive evidence. Later deep-company reviews should use annual reports, exchange announcements, official investor-relations materials, product certifications, customer qualification evidence, market-share evidence, segment margins, cost-curve evidence, and reputable institutional research where needed.
