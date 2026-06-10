# 1. A-Share Remaining State Banks Peer-Group Review

## 1.1 Purpose

This group completes the remaining unreviewed state-owned banks after the accepted bank standard had already retained 招商银行, 宁波银行, 邮储银行, and 常熟银行 while excluding other banks from the quality watchlist.

## 1.2 Retention Standard

1. Keep the explicit accepted bank watchlist unless a bank has a distinct customer, liability, risk-selection, or operating model not already covered by the retained names.
2. Reject large stable state banks from this business-quality watchlist when the case is mainly system importance, dividend stability, or balance-sheet scale rather than differentiated compounding quality.

## 1.3 Decisions

The structured decision file is `data/processed/a_share_state_banks_remaining_peer_group_decisions.csv`.

Direct watch:

- None

Boundary watch after analyst judgment:

- None

3 companies are rejected for now out of 3 reviewed rows. Rejections are company-specific and recorded in the CSV; common reasons include weak differentiation, commodity or project-cycle exposure, low-barrier products, ST/restructuring risk, or stronger retained peers covering the same thesis.

## 1.4 Sources

This first-pass peer-group review uses the local full-coverage scoring evidence and company-profile evidence already stored in `data/processed/a_share_company_triage_reviews.csv`, `data/processed/a_share_full_coverage_scores.csv`, and `data/interim/a_share_company_profiles.csv` as discovery metadata. Each decision row records official exchange disclosure landing pages for annual reports and announcements. Aggregator company introductions are not treated as decisive evidence. Later deep-company reviews should use annual reports, exchange announcements, official investor-relations materials, product certifications, customer qualification evidence, market-share evidence, segment margins, cost-curve evidence, and reputable institutional research where needed.
