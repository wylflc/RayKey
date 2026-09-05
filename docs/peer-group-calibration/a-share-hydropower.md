# 1. A-Share Hydropower Peer-Group Review

## 1.1 Purpose

This note records the company-by-company review for `公用事业-电力-水电`.

The group mixes world-class river-cascade platforms, basin-level hydropower operators, integrated power companies with scarce hydropower exposure, pumped-storage platforms, regional hydropower operators, local power and water utilities, and diversified local utility companies. The review separates irreplaceable long-life water resources from ordinary local utility stability.

## 1.2 Retention Standard

1. Retain direct-watch companies when they own irreplaceable large-cascade hydropower assets, basin-level water-resource control, high-quality integrated power platforms whose core value is scarce hydropower, or pumped-storage/grid-regulation platforms with institutional scarcity.
2. Retain boundary cases when they have high-quality underlying hydropower assets through an investment-holding structure, strong regional hydropower operations, or focused smaller hydropower assets with strong operating quality.
3. Reject local power/water utilities, small hydropower asset owners, regional integrated utilities, and diversified local utility companies when stability is not paired with scale, resource scarcity, flow-regulation advantage, dispatch role, or superior economics.
4. Stable cash flow is not enough. A watched hydropower company must show that a well-funded entrant cannot replicate its river basin, project approvals, reservoir/cascade position, grid-dispatch role, low-cost asset base, or long-life cash flow.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_hydropower_peer_group_decisions.csv`.

Direct watch:

- 长江电力
- 华能水电
- 国投电力
- 南网储能

Boundary watch after analyst judgment:

- 川投能源
- 桂冠电力
- 黔源电力

The remaining companies are rejected for now because they are regional integrated utilities, local power and water utilities, small hydropower asset owners, or diversified local utility companies whose stability does not rise to a scarce hydropower moat.

## 1.4 Sources

This first-pass group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/archive/a_share_company_profiles.csv`. The decision rows preserve source URLs. Final deep-company reviews should replace aggregator discovery URLs with annual reports, installed-capacity and river-basin breakdowns, utilization-hour data, regulated power-price disclosures, reservoir/cascade dispatch data, pumped-storage tariff and capacity-price records, and reputable institutional research where needed.
