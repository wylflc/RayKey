# 1. A-Share Other Electrical Equipment Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `电气设备-其他电气设备-其他电气设备`.

This is a noisy residual peer group. It includes high-voltage insulation materials, smart-grid diagnostics, intelligent controllers, industrial power electronics, PV trackers, PV modules, wind turbines, energy-storage systems, consumer electrical brands, rail-signal systems, electrical contact materials, battery interconnects, appliance components, PV junction boxes, electrical cabinets, distributors, and ST transition cases. The review therefore judges company-level capability first and only then applies the peer-group label.

## 1.2 Retention Standard

1. Retain direct-watch companies when they have strong category control, such as high-voltage/UHV insulation materials, a dominant consumer electrical brand and channel system, a global PV tracker platform, a misclassified global PV platform, industrial digital-printing equipment with consumables, or a diversified power-electronics platform.
2. Retain boundary cases when a company has real but narrower power-system safety, transformer insulation, power automation, smart distribution-grid, industrial power-supply, power-electronics testing, rail-signal, linear-drive, electrical contact-material, battery-interconnect, energy-storage, or wind-turbine capability.
3. Reject ordinary PV junction boxes and connectors, low-voltage electrical followers, electrical distributors, electrical cabinets, appliance components, ventilation systems, micro-switches, special transformers without category control, wind heavy-fabrication suppliers, small distributed-PV operators, ST transition stories, and diversified electrical-solution companies without one clearly leading segment.
4. When a company is obviously misclassified, apply the stronger company-level rule. A solar, wind, consumer-electrical, industrial-equipment, or rail-safety platform should not be rejected merely because it appears in a residual electrical-equipment group.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_other_electrical_equipment_peer_group_decisions.csv`.

Direct watch:

- 麦克奥迪
- 公牛集团
- 中信博
- 天合光能
- 宏华数科
- 麦格米特

Boundary watch after analyst judgment:

- 明阳智能
- 山大电力
- 广信科技
- 科汇股份
- 振邦智能
- 英杰电气
- 英威腾
- 宏力达
- 派能科技
- 爱科赛博
- 辉煌科技
- 捷昌驱动
- 福达合金
- 西典新能

The remaining companies are rejected for now because they are ordinary component manufacturing, PV connector or frame suppliers, low-voltage electrical followers, distributors, appliance or ventilation equipment companies, small automation-equipment suppliers, heavy-fabrication wind suppliers, mixed electrical-solution companies, or ST/transition cases without scarce company-level capability.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. Each decision row also adds the relevant exchange disclosure landing page and official company website when available. Later deep-company reviews should use annual reports, exchange announcements, State Grid and Southern Grid tender evidence, product certifications, high-voltage and UHV project references, customer qualification evidence, market-share evidence, segment margins, and reputable institutional research.
