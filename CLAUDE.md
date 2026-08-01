# AShareQuant Agent Instructions

Research and data analysis for listed companies in mainland China and Hong Kong markets.

## Where The Standards Live

- **`docs/000_Ashare_workflow.md`** is the master execution spec for the entire A-share pipeline (quality triage → tiering → valuation pool → daily volume/price scan → pretrade gate → holdings monitoring/sell scan). Route through its §0 task-routing table and execute the matching section without asking the user to re-explain the process. **Standards live only in that file.** If one looks wrong, edit it first (§15), then re-run — never override or restate its thresholds elsewhere.
- **`docs/personal-investment-system-v1.zh.md`** is the governing standard for investment judgment: strategy classification, watchlist strictness, position discipline, and the §17 behavioural red lines. Apply it strictly; the watchlist is meant to be small.
- **`docs/Ashare_workflow_open_issues.md`** registers confirmed-but-unfixed defects. Check it before trusting a mechanism it lists.
- For single-company, stock-defence, watchlist, valuation, or position-sizing analysis, use the project-level `stock-analysis` skill.

Treat the latest user request and committed project docs as the source of truth for current priorities. Do not turn transient requirements into reusable skill rules.

## Working Rules

- Read the relevant files before editing — especially `README.md`, `CONTEXT.md`, existing ADRs, and nearby code.
- Keep changes scoped to the request and match the repository's existing style.
- Do not add dependencies, data providers, databases, schedulers, or external services unless the request clearly needs them.
- `docs/xzy/` holds another person's investment-system materials. Do not use or reference it in analysis unless the user explicitly cites it.
- **`000_` filename prefix is reserved for files the user opens and reads directly** — it exists to keep those files sorted to the top. Do not add it to design notes, audits, changelogs, issue registers, or any other agent/program working document. Currently prefixed: `docs/000_Ashare_workflow.md`, `data/processed/000_a_share_core_valuation_pool.md`, `000_a_share_watchlist_quality_tiers.md`, `000_daily_scan_log.md`.
- After any completed file-change batch, create a git commit before the final response. Do not push unless explicitly asked.
- Git commit messages: one short sentence. No body, trailers, attribution, co-author tags, or any tool-generated signature.
- Never store API keys, tokens, cookies, account identifiers, or paid-data credentials in the repository.

## Validation

Run the most targeted useful check after changes. When a check needs network access, paid credentials, or unavailable market-data services, say so plainly and validate the local parts instead. Do not claim data coverage or analysis correctness without a reproducible check behind it.
