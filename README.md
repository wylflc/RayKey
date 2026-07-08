# AShareQuant

AShareQuant is a research and data-analysis project for listed companies in mainland China, Hong Kong, and U.S. equity markets. The primary focus is A-share investment research; the Hong Kong and U.S. universe/evidence pipelines are retained for later rounds.

The project supports a reproducible equity-research workflow: build an investable universe, keep only companies with durable business quality, exclude overpriced securities, trigger entries from right-side volume-price signals, and keep every conclusion auditable.

## Primary Workflow (A-share)

`docs/000_Ashare_workflow.md` is the executable specification for the five-stage A-share loop. Its §0 routing table maps instructions to modules and scripts.

1. Quarterly full-market quality review: round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`, ADR-0006), then L1-L5 quality tiering for worth-attention companies (§5.7/§5.7.1/§5.8).
2. Valuation screening for L1/L2 core-quality companies, materialized into the core valuation pool.
3. Rolling updates after financial-report disclosures.
4. Daily volume-price scan producing buy candidates from the core valuation pool.
5. Daily holdings monitoring and sell scan.

A full-universe round-1 rescan is in progress; `docs/round1-rescan-progress.md` holds the live snapshot and handoff instructions. Every reviewed conclusion is appended to `data/processed/a_share_workflow_decision_log.csv`.

The personal investment system in `docs/personal-investment-system-v1.zh.md` (Chinese, canonical) is the default standard for all equity analysis.

## Repository Layout

- `docs/000_Ashare_workflow.md` — main A-share workflow specification.
- `docs/personal-investment-system-v1.zh.md` — personal investment rulebook.
- `docs/round1-rescan-progress.md` — round-1 rescan progress and handoff.
- `docs/peer-group-calibration/` — per-industry calibration narratives; the audit trail of how the round-1 rules were formed.
- `docs/moat-scoring-rubric.md` — dimensional triage rubric, still the standard for the Hong Kong / U.S. full-coverage scorers.
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
python3 scripts/build_a_share_full_rescan_queue.py        # round-1 rescan worklist
python3 scripts/build_quarterly_quality_review_queue.py   # quarterly review queue
python3 scripts/build_report_update_queue.py              # post-disclosure update queue
```

Evidence (resumable interim CSVs used during triage and tiering):

```bash
python3 scripts/fetch_a_share_research_evidence.py
```

Valuation pool materialization and daily scans (see workflow §6.7, §8.3, §14):

```bash
python3 scripts/build_a_share_core_valuation_pool.py --as-of YYYY-MM-DD
python3 scripts/screen_daily_volume_price_signals.py --as-of YYYY-MM-DD
python3 scripts/scan_holdings_sell_signals.py --as-of YYYY-MM-DD
python3 scripts/backtest_signal_replay.py --as-of YYYY-MM-DD --symbols CODE1,CODE2
```

`scripts/workflow_decision_log.py` is the shared decision-log helper imported by the scan/pool scripts.

## Hong Kong / U.S. Pipelines (retained)

```bash
python3 scripts/fetch_hong_kong_universe.py --output data/raw/hong_kong_securities.csv
python3 scripts/fetch_us_universe.py --output data/raw/us_securities.csv
python3 scripts/fetch_hong_kong_research_evidence.py
python3 scripts/fetch_us_research_evidence.py
python3 scripts/run_hong_kong_full_coverage_scoring.py
python3 scripts/run_us_full_coverage_scoring.py
```

The fetchers write research queues, company profiles, and financial indicators into `data/interim/`. The scorers apply the rubric in `docs/moat-scoring-rubric.md` as a baseline triage aid; scoring output is not a final watchlist decision (ADR-0002/0003/0004). The U.S. pipeline keeps ETF/ETN/unit/warrant/preferred instruments with an explicit not-applicable status instead of scoring them as listed companies.

## Archived: 2026-06 Two-Layer Review Round

The first A-share full-coverage round (two-layer review, peer-group calibration, authoritative per-company deep review, and L1/L2 valuation) is complete and closed:

- `data/archive/2026-06-two-layer-review/a_share_final_watchlist.csv` — final watch decisions with reasons and dimensional scores.
- `data/processed/a_share_watchlist_quality_tiers.csv` / `.md` — deep-review L1-L5 tiers (1,661 companies).
- `data/processed/a_share_focus_watchlist_l1_l2_valuation.csv` — L1/L2 valuation results.

Per workflow §5.4.6, these prior-round files remain transition references (the core valuation pool and daily scans still read the tier/valuation files) until the round-1 rescan finishes, after which tiering, valuation, and the core pool must be rebuilt. The cross-round index above is the convenient merged view of prior and current conclusions. The narrative record of how calibration rules evolved stays in `docs/peer-group-calibration/`.

## Principles

- Keep raw source records separate from normalized data and derived signals: `data/raw/` first, `data/interim/` second, `data/processed/` last.
- Preserve data provenance: provider, retrieval time, raw identifier, exchange, currency, reporting period, and adjustment policy.
- Distinguish listed companies from their tradable securities, share classes, exchanges, and identifiers.
- Keep business-quality screening separate from valuation assessment; a watchlist is a research output, not a buy list.
- Company-level watch/reject decisions represent analyst/model judgment applied company by company, never numeric thresholds alone (ADR-0004).
- Avoid committing credentials, paid-data access details, cookies, or private account identifiers.

## Project Docs

- `AGENTS.md` contains repository-specific instructions for coding agents.
- `CONTEXT.md` defines the stable domain language used by the project.
- `.agents/` and `.codex/` are local agent workspaces and are intentionally ignored by Git.

## Development Workflow

Read the project docs before making changes. After modifying files, run the most targeted useful local check available and commit the completed change batch. Do not push to a remote unless explicitly requested.
