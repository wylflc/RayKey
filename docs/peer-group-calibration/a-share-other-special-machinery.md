# 1. A-Share Other Special Machinery Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `机械设备-专用设备-其他专用机械`.

The peer group is broad: it contains semiconductor process tools, PCB equipment, photovoltaic and lithium process equipment, optical sorting, industrial X-ray and machine vision, explosion-proof safety equipment, high-purity process systems, nuclear equipment, traditional packaging and construction machinery, oilfield equipment, automotive automation, and many project-based special-machine companies. A threshold-only score would be misleading, so the final decision file uses peer-group judgment.

## 1.2 Retention Standard

1. Retain direct-watch companies when they own a hard-to-replicate process-tool platform, clear global or domestic category leadership, scarce certification/qualification barriers, or a technology moat that a well-funded entrant cannot quickly copy.
2. Retain boundary cases when the company owns a distinct niche moat, validated process know-how, scarce customer qualification, high normalized margin potential, or cross-industry capability that is not already fully covered by a stronger retained peer.
3. Reject ordinary project-based special-machine companies when the main advantage is engineering delivery, customer projects, or manufacturing scale rather than scarce technology, process control, qualification, or brand/channel power.
4. Reject weaker followers when a stronger retained peer already covers the durable thesis in the same process step or comparable niche.
5. Do not reject a company only because current profits are weak; retain it when the evidence supports scarce capability, hard validation, or long-cycle technology accumulation.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_other_special_machinery_peer_group_decisions.csv`.

Direct watch:

- 软控股份
- 美亚光电
- 英维克
- 豪迈科技
- 伊之密
- 美畅股份
- 大族数控
- 浙江鼎力
- 华荣股份
- 芯源微
- 中科飞测
- 芯碁微装
- 奥特维
- 东威科技
- 屹唐股份

Boundary watch after analyst judgment:

- 精工科技
- 融发核电
- 岱勒新材
- 国安达
- 光力科技
- 赢合科技
- 震裕科技
- 曼恩斯特
- 盘古智能
- 尚水智能
- 超研股份
- 宏工科技
- 科达制造
- 中国电研
- 美腾科技
- 至纯科技
- 步科股份
- 华兴源创
- 杭可科技
- 深科达
- 新益昌
- 骄成超声
- 凌云光
- 利元亨
- 日联科技
- 高测股份
- 联赢激光
- 海目星
- 汉邦科技
- 耐科装备
- 弘亚数控
- 泰林生物

The remaining companies are rejected for now because they are ordinary project-based equipment vendors, lower-barrier traditional machinery businesses, cyclical oilfield/construction/building-material equipment companies, packaging or furniture equipment companies with limited irreproducibility, automotive automation integrators, or weaker followers already covered by stronger retained peers.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with direct annual reports, exchange filings, product-certification evidence, customer/project evidence, and reputable institutional research where needed.
