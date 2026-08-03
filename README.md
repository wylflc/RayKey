# AShareQuant

AShareQuant is a research and data-analysis project for listed companies in mainland China, Hong Kong, and U.S. equity markets. The primary focus is A-share investment research; the Hong Kong and U.S. universe/evidence pipelines are retained for later rounds.

The project supports a reproducible equity-research workflow: build an investable universe, keep only companies with durable business quality, exclude overpriced securities, trigger entries from right-side volume-price signals, and keep every conclusion auditable.

## Primary Workflow (A-share)

`docs/000_Ashare_workflow.md` is the executable specification for the five-stage A-share loop. Its §0 routing table maps instructions to modules and scripts.

1. Quarterly full-market quality review: round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`, ADR-0006), then three-tier quality tiering (L1 strong / L2 medium / L3 weak moat) for worth-attention companies (§5.7/§5.7.1/§5.8, workflow v1.27).
2. Valuation screening across the worth-attention set, materialized into the core valuation pool (core layer = L1/L2, tactical = L3).
3. Rolling updates after financial-report disclosures.
4. Daily volume-price scan producing buy candidates from the core valuation pool.
5. Daily holdings tracking: per-holding announcement/news search plus a valuation refresh (workflow v2.05 reduced this stage from a sell-decision engine to plain tracking; the stop price is the only mechanical rule left, and the buy-side §10 gate retired in the same revision — the pipeline now ends at candidates).

The full-universe round-1 rescan is complete (5,653 companies triaged as of 2026-07-09: 261 worth_attention / 5,332 boundary_pending / 60 garbage); `docs/archive/round1-rescan-progress.md` holds the final snapshot. Tiering over that set was rebuilt on 2026-08-01 under workflow v1.27 (L1 21 / L2 231 / L3 9, all evidence-reviewed). Every reviewed conclusion is appended to `data/processed/a_share_workflow_decision_log.csv`.

The personal investment system in `docs/000_personal-investment-system-v1.zh.md` (Chinese, canonical) is the default standard for all equity analysis.

## Repository Layout

- `docs/000_Ashare_workflow.md` — main A-share workflow specification.
- `docs/000_personal-investment-system-v1.zh.md` — personal investment rulebook.
- `docs/Ashare_quality_rubric.md` — the Q1/Q2 scoring detail behind workflow §5.7 tier assignment. Rule-bearing content was hoisted into workflow §5.7.4 in v2.00; this file keeps the scoring recipe and the decided cases.
- `docs/Ashare_workflow_changelog.md` — per-version workflow history; `docs/Ashare_workflow_open_issues.md` — confirmed-but-unfixed defects.
- `docs/archive/` — completed process logs, one-off audits, and implemented design docs. Not inputs to any live flow.
- `docs/peer-group-calibration/` — per-industry calibration narratives; the audit trail of how the round-1 rules were formed.
- `docs/adr/` — architecture decision records; ADR-0006 defines the current round-1 triage standard.
- `data/raw/` — immutable universe snapshots (ADR-0001).
- `data/interim/` — resumable work queues and fetched evidence.
- `data/processed/` — current workflow outputs and the decision log.
- `data/archive/` — closed-round results kept for cross-round reference.
- `scripts/` — deterministic workflow scripts; company judgment is model work specified in the workflow doc, not thresholds in scripts (ADR-0004/0006).

## Cross-Round Company Analysis Index

Conclusions about one company accumulate across rounds. The merged one-row-per-company view:

```bash
python3 scripts/build_a_share_company_analysis_index.py
```

It writes `data/processed/a_share_company_analysis_index.csv` (full universe) and `.md` (reading view). Columns merge the current round-1 triage (`round1_*`), the closed 2026-06 two-layer review round (`prior_*`: screening decision, deep-review L1-L5 tier, L1/L2 valuation, core-pool eligibility), and a per-company decision-log rollup. The script creates no new conclusions and does not write to the decision log.

## A-share Scripts

Universe and queues:

```bash
python3 scripts/fetch_a_share_universe.py --output data/raw/a_share_securities.csv
python3 scripts/build_quarterly_quality_review_queue.py   # quarterly review queue
python3 scripts/build_report_update_queue.py              # post-disclosure update queue
```

Valuation evidence and per-company dossiers (workflow §6.5.7 — the only path that produces a tradable band):

```bash
python3 scripts/fetch_a_share_valuation_evidence.py       # consensus, financials, coverage counts
python3 scripts/build_company_dossier_readmes.py --check   # dossier CSV -> README, diff only
python3 scripts/build_valuation_band_cards.py             # dossier -> band cards + column self-check
python3 scripts/validate_valuation_bands.py               # gate before pool materialization
```

Valuation pool materialization and daily scans (see workflow §6.7, §8.3, §14):

```bash
python3 scripts/build_a_share_core_valuation_pool.py --as-of YYYY-MM-DD
python3 scripts/screen_daily_volume_price_signals.py --as-of YYYY-MM-DD
python3 scripts/track_holdings_daily.py --as-of YYYY-MM-DD
python3 scripts/backtest_signal_replay.py --as-of YYYY-MM-DD --symbols CODE1,CODE2
```

`scripts/workflow_decision_log.py` is the shared decision-log helper imported by the scan/pool scripts; it parses the workflow version from the spec's title line rather than hard-coding it.

## Hong Kong / U.S. Pipelines (retired in v2.00)

The full-coverage Hong Kong and U.S. scorers and their fetchers now live in `scripts/archive/`, and their rubric
`docs/moat-scoring-rubric.md` in `docs/archive/`. Overseas coverage runs through workflow §6.8 instead: only
user-named companies are tiered and banded, into `data/processed/overseas_watchlist_valuation.csv`, rendered as
an appendix to the pool reading view and never buyable. See `scripts/archive/README.md` to restore them.

## Archived: 2026-06 Two-Layer Review Round

The first A-share full-coverage round (two-layer review, peer-group calibration, authoritative per-company deep review, and L1/L2 valuation) is complete and closed:

- `data/archive/2026-06-two-layer-review/a_share_final_watchlist.csv` — final watch decisions with reasons and dimensional scores.
- `data/processed/a_share_watchlist_quality_tiers.csv` / `.md` — deep-review L1-L5 tiers (1,661 companies).
- `data/processed/a_share_focus_watchlist_l1_l2_valuation.csv` — L1/L2 valuation results.

The round-1 rescan finished on 2026-07-09 and tiering, valuation, and the core pool were all rebuilt on top of it (workflow v1.27/v1.28), so these files are now closed-round records rather than transition references. The cross-round index above is the convenient merged view of prior and current conclusions. The narrative record of how calibration rules evolved stays in `docs/peer-group-calibration/`.

## Principles

- Keep raw source records separate from normalized data and derived signals: `data/raw/` first, `data/interim/` second, `data/processed/` last.
- Preserve data provenance: provider, retrieval time, raw identifier, exchange, currency, reporting period, and adjustment policy.
- Distinguish listed companies from their tradable securities, share classes, exchanges, and identifiers.
- Keep business-quality screening separate from valuation assessment; a watchlist is a research output, not a buy list.
- Company-level watch/reject decisions represent analyst/model judgment applied company by company, never numeric thresholds alone (ADR-0004).
- Avoid committing credentials, paid-data access details, cookies, or private account identifiers.

## Project Docs

- `CLAUDE.md` contains repository-specific instructions for coding agents (`AGENTS.md` is a pointer to it).
- `CONTEXT.md` defines the stable domain language used by the project.
- `docs/000_Ashare_workflow.md` is the master execution spec for the A-share pipeline; `docs/000_personal-investment-system-v1.zh.md` governs investment judgment.
- `.agents/` and `.codex/` are local agent workspaces and are intentionally ignored by Git.

## Development Workflow

Read the project docs before making changes. After modifying files, run the most targeted useful local check available and commit the completed change batch. Do not push to a remote unless explicitly requested.
