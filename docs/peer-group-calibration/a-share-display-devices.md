# 1. A-Share Display Devices Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `电子设备-电子器件-显示器件`.

The group mixes global panel platforms, small and automotive display specialists, substrate glass, polarizers, AMOLED and microdisplay companies, display automation equipment, optical/touch/coating materials, ordinary LCD modules, backlights, LED display projects, consumer electronics assemblers, ST cases, and mixed legacy businesses. The review separates hard process, yield, customer-qualification, and materials barriers from lower-barrier module assembly and project-driven display products.

## 1.2 Retention Standard

1. Retain direct-watch companies when they own global display-panel leadership, differentiated small/automotive/professional display platforms, substrate glass/material capability, or key display materials with process and customer-validation barriers.
2. Retain boundary cases when they have a credible AMOLED, microdisplay, polarizer/optical-film, display-automation-equipment, vacuum-coating, ITO/touch, cover-glass, or micro/nano optical niche that is not fully covered by a stronger retained peer.
3. Reject ordinary display modules, backlights, light-guide plates, low-margin monitor/TV assembly, LED display projects, mixed electronics without category control, ST cases, and legacy display businesses without evidence of durable process or customer-lock-in advantages.
4. Treat current losses as secondary when scarce display capability is real, but use normalized margin weakness and customer bargaining pressure as evidence against low-barrier modules or undifferentiated electronic manufacturing.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_display_devices_peer_group_decisions.csv`.

Direct watch:

- 京东方Ａ
- 深天马Ａ
- 彩虹股份
- 三利谱

Boundary watch after analyst judgment:

- 凯盛科技
- 长信科技
- 联得装备
- 深纺织Ａ
- 和辉光电
- 纬达光电
- 莱宝高科
- 苏大维格
- 视涯科技

The remaining companies are rejected for now because they are ordinary display modules, backlight/light-guide suppliers, low-margin monitor/TV or consumer-electronics assemblers, LED display project businesses, mixed electronics companies without clean display-platform control, ST cases, or legacy display businesses that do not show enough category leadership versus retained panel, material, AMOLED, microdisplay, and equipment candidates.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with direct annual reports, exchange filings, product documentation, panel-customer qualification evidence, materials/process evidence, and reputable institutional research where needed.

## 1.5 New-Standard Recalibration (ADR-0006)

Re-applying the round-1 standard (operation-workflow §5.4) to the core panel makers — stricter than §1.3, since worth_attention now requires a structurally durable, hard-to-replicate moat:

| Class | Companies | Basis |
| --- | --- | --- |
| worth_attention (2) | 京东方A, TCL科技 | Consolidated large-panel oligopoly leaders. Korea's irreversible LCD exit + a $10B+ leading-edge fab barrier make the scale/capital/OLED moat objectively hard to replicate; cyclicality is discounted at tiering/valuation, not a round-1 excluder. |
| boundary_pending (6) | 深天马A (auto/small-panel niche, sub-scale); 维信诺, 和辉光电 (AMOLED challengers, loss-making, sub-scale); 彩虹股份 (substrate-glass import-substitution niche + sub-scale panel); 龙腾光电 (small commodity LCD); 华映科技 (governance disaster under the former parent, now under SOE restructuring) | Reversible; re-review on proven scale/profit, niche scale-up, or restructuring outcome. |
| garbage | none | Post-consolidation the panel industry is not structurally hopeless; the one governance-troubled name is under new control + restructuring, so boundary rather than permanent garbage. |

Calibration rules distilled into operation-workflow §5.4.5: (6) for capex-cyclical tech-manufacturing, an irreversible structural consolidation + an objectively large capital/scale/tech barrier can grant worth_attention before through-cycle profitability is proven — different from the baijiu rule because the moat's durability here is structural rather than in doubt; (7) a governance disaster under a former controlling shareholder, now under new control and restructuring, is boundary (control change = re-review trigger), not permanent garbage.

Verify against filings before freezing (panel-customer qualification, OLED capacity/yield, 华映科技 restructuring status).
