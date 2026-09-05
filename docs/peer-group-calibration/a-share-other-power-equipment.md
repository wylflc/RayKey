# 1. A-Share Other Power Equipment Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `电气设备-电源设备-其他电源设备`.

The group mixes energy-storage systems, high-reliability military and aerospace power supplies, power-electronics testing equipment, clean-energy thermal equipment, power-management ICs, photovoltaic transformers and magnetic components, defense power-electronics cases, charging power modules, generator sets, explosion-proof electrical equipment, communication power supplies, ST cases, and companies already retained under battery materials. The review separates high-validation power platforms from ordinary power equipment.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have large-scale storage system capability, software/safety validation, project delivery, or high-reliability aerospace/defense power-supply qualification.
2. Retain boundary cases when they have power-electronics testing equipment, clean-energy thermal equipment, power-management ICs, renewable magnetic components, or defense power-electronics exposure, but with narrower market scale or stronger cyclicality.
3. Reject charging-power suppliers, generator-set companies, niche explosion-proof equipment, smaller communication-power suppliers, ST cases, and companies whose watch thesis belongs to battery materials rather than power equipment.
4. A watched company must show system safety validation, software/control capability, high-reliability qualification, power-electronics know-how, or customer certification. Ordinary power conversion products are not enough.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_other_power_equipment_peer_group_decisions.csv`.

Direct watch:

- 海博思创
- 新雷能

Boundary watch after analyst judgment:

- 科威尔
- 西子洁能
- 晶丰明源
- 伊戈尔
- 甘化科工

The remaining companies are rejected for now in this peer group because they are battery-material companies already retained elsewhere, competitive charging-power suppliers, mature generator-set companies, niche explosion-proof equipment suppliers, smaller communication-power suppliers, or ST cases.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, project delivery records, safety and certification records, power-electronics product data, defense qualification disclosures, customer concentration, segment margins, and reputable institutional research where needed.
