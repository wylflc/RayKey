# 1. A-Share Industry Application Software Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `信息技术-计算机软件-行业应用软件`.

The group contains very different business models: EDA, industrial control software, energy IT, cybersecurity, financial software, construction software, CAD/CAE/PDF products, GIS, healthcare IT, government IT, railway systems, and project-based system integrators. A single score cutoff is therefore inappropriate.

## 1.2 Retention Standard

1. Retain software anchors when workflow ownership, customer switching cost, domain data, product depth, engineering scarcity, or regulated customer validation makes replacement difficult.
2. Retain boundary companies only when the niche is distinct and not already covered by a stronger retained platform.
3. Reject project-heavy system integrators and generic vertical-software vendors when the advantage can be replicated by capital, hiring, relationships, or larger platform vendors.
4. Reject weaker financial, cybersecurity, government, and healthcare software copies when a stronger retained peer already covers the attention slot.
5. Defer aerospace and defense-software cases when the disclosure standard differs materially from civilian application software.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_industry_application_software_peer_group_decisions.csv`.

Direct watch:

- 威胜信息
- 远光软件
- 深信服
- 华大九天
- 科大讯飞
- 恒生电子
- 广联达
- 宝信软件
- 中控技术

Boundary watch after analyst judgment:

- 国能日新
- 汉朔科技
- 中科星图
- 概伦电子
- 石基信息
- 思维列控
- 四维图新
- 中望软件
- 中科江南
- 福昕软件
- 索辰科技
- 超图软件

The remaining reviewed companies are rejected for now because they are more project-heavy, more replaceable, more customer-concentrated, or weaker copies of retained platforms.

## 1.4 Deferred Questions

Aerospace and defense-software cases are recorded in `docs/peer-group-calibration/a-share-pending-questions.md` for later dedicated handling.

## 1.5 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. These rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with direct annual reports, exchange announcements, company investor-relations materials, or reputable institutional research where needed.
