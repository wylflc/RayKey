# AShareQuant

AShareQuant is a research and data-analysis project for listed companies in mainland China, Hong Kong, and U.S. equity markets. The primary focus is A-share investment research; the Hong Kong and U.S. universe/evidence pipelines are retained for later rounds.

The project supports a reproducible equity-research workflow: build an investable universe, keep only companies with durable business quality, exclude overpriced securities, trigger entries from right-side volume-price signals, and keep every conclusion auditable.

## Primary Workflow (A-share)

`docs/000_Ashare_workflow.md` is the executable specification for the five-stage A-share loop. Its §0 routing table maps requests to the current sections and scripts; this README intentionally does not duplicate operational parameters or ordered command chains.

1. Quarterly full-market quality review: round-1 three-class triage (`worth_attention` / `boundary_pending` / `garbage`, ADR-0006), then three-tier quality tiering (L1 strong / L2 medium / L3 weak moat) for worth-attention companies (workflow §5).
2. Valuation screening across the worth-attention set, materialized into the core valuation pool (core layer = L1/L2, tactical = L3).
3. Rolling updates after financial-report disclosures.
4. Daily volume-price scan producing buy candidates from the core valuation pool.
5. Daily execution and holdings tracking under workflow §9 and §11.

The completed full-universe rescan snapshot is in `docs/archive/round1-rescan-progress.md`. Current triage and tier counts must be read from the live processed CSVs rather than copied into this README; every reviewed conclusion is appended to `data/processed/a_share_workflow_decision_log.csv`.

The personal investment system in `docs/000_personal-investment-system-v1.zh.md` (Chinese, canonical) is the default standard for all equity analysis.

## Repository Layout

- `docs/000_Ashare_workflow.md` — main A-share workflow specification.
- `docs/000_personal-investment-system-v1.zh.md` — personal investment rulebook.
- `docs/Ashare_quality_rubric.md` — scoring detail and decided cases behind workflow §5.7; the workflow keeps the current hard rules.
- `docs/Ashare_workflow_changelog.md` — per-version workflow history; `docs/Ashare_workflow_open_issues.md` — confirmed-but-unfixed defects.
- `docs/archive/` — completed process logs, one-off audits, and implemented design docs. Not inputs to any live flow.
- `docs/peer-group-calibration/` — per-industry calibration narratives; the audit trail of how the round-1 rules were formed.
- `docs/adr/` — architecture decision records; ADR-0006 defines the current round-1 triage standard.
- `data/raw/` — immutable universe snapshots (ADR-0001). Prices, quarterly financials and research
  reports are `.gitignore`d: ~890 MB, fully re-fetchable by the `fetch_*` scripts.
- `data/interim/` — resumable work queues and fetched evidence.
- `data/processed/` — current workflow outputs and the decision log.
- `data/companies/<code>_<name>/` — **everything human-readable about one stock lives here**: the
  valuation dossier (`README.md`), the quarterly financial ledger (`fundamentals.md`) and the
  research ledger. Consolidated in workflow v2.92; the ledgers were previously under
  `data/processed/fundamentals/`.
- `data/archive/` — closed-round results kept for cross-round reference.
- `scripts/` — deterministic workflow scripts; company judgment is model work specified in the workflow doc, not thresholds in scripts (ADR-0004/0006).
- `scripts/archive/` — retired scripts. Each row in its README carries an archived-on date and a
  delete-after date (3 months); nothing is due before 2026-11-02.

**Derived artifacts are disposable.** Backtests and valuation-band variants regenerate from the
scripts, so they are `.gitignore`d and cleaned with `scripts/clean_derived_artifacts.py`
(reports by default, `--apply` to act). Before the 2026-08-14 sweep the repo carried 5.7 GB of them
across 57k files; historical scan readings are consolidated into
`data/processed/backtest/scan_summaries.csv`. Multi-config sweeps go through
`scripts/sweep_backtest_configs.py`, which pins the workflow §9.7.1.2 command as its baseline
rather than having each round retype it.

## Cross-Round Company Analysis Index

Conclusions about one company accumulate across rounds. The merged one-row-per-company view:

```bash
python3 scripts/build_a_share_company_analysis_index.py
```

It writes `data/processed/a_share_company_analysis_index.csv` (full universe) and `.md` (reading view). Columns merge the current round-1 triage (`round1_*`), a `prior_*` block, and a per-company decision-log rollup. The script creates no new conclusions and does not write to the decision log.

**Read the `prior_*` prefix carefully — it is not uniform.** Only `prior_final_decision` / `prior_watch_selection_route` / `prior_decision_reason` come from the closed 2026-06 round. `prior_quality_tier` / `prior_tier_reason` / `prior_strategy_tag` / `prior_valuation_*` / `prior_core_pool_eligible` are read from the **current** live files (`a_share_watchlist_quality_tiers.csv`, `a_share_focus_watchlist_l1_l2_valuation.csv`, `a_share_core_valuation_pool.csv`), so they carry today's L1–L3 tiers, not the retired L1–L5 scale. The prefix is a leftover from when those files were snapshots; the column names are kept to avoid breaking consumers.

## A-share Scripts

Universe and queues:

```bash
python3 scripts/fetch_a_share_universe.py --output data/raw/a_share_securities.csv
python3 scripts/build_quarterly_quality_review_queue.py --as-of YYYY-MM-DD   # quarterly review queue
python3 scripts/build_report_update_queue.py --market A_SHARE --as-of YYYY-MM-DD  # post-disclosure update queue
```

Valuation, pool materialization, daily scans, holdings tracking, and backtests must use the current ordered commands in workflow §6.7, §8.2, §9.1, §11, and §12. They are not copied here so that changing one operational mouth cannot leave a stale second version.

`scripts/workflow_decision_log.py` is the shared decision-log helper imported by the scan/pool scripts; it parses the workflow version from the spec's title line rather than hard-coding it.

## Hong Kong / U.S. Pipelines (retired in v2.00)

The full-coverage Hong Kong and U.S. scorers and their fetchers now live in `scripts/archive/`, and their rubric
`docs/moat-scoring-rubric.md` in `docs/archive/`. Overseas coverage runs through workflow §6.8 instead: only
user-named companies are tiered and banded, into `data/processed/overseas_watchlist_valuation.csv`, rendered as
an appendix to the pool reading view and never buyable. See `scripts/archive/README.md` to restore them.

## Archived: 2026-06 Two-Layer Review Round

The first A-share full-coverage round (two-layer review, peer-group calibration, authoritative per-company deep review, and L1/L2 valuation) is complete and closed:

- `data/archive/2026-06-two-layer-review/a_share_final_watchlist.csv` — final watch decisions with reasons and dimensional scores.

(`data/processed/a_share_focus_watchlist_l1_l2_valuation.csv` was listed here until 2026-08-03 but is **not** a closed-round record — it is the live valuation table the band chain writes and the pool reads. Its name is a leftover from that round.)

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
