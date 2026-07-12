# AShareQuant Agent Instructions

## Project Focus

AShareQuant is a research and data-analysis project for listed companies in mainland China and Hong Kong markets. Treat the latest user request and committed project docs as the source of truth for current priorities; do not turn transient requirements into reusable skill rules.

**Core workflow file**: `docs/000_Ashare_workflow.md` is the master execution spec for the entire A-share pipeline (quality triage → tiering → valuation pool → daily volume/price scan → pretrade gate → holdings monitoring/sell scan). For any such task, route through its §0 task-routing table and execute per the matching section without asking the user to re-explain the process. Standards live only in that file: if one looks wrong, edit it first (§15), then re-run; never override or restate its thresholds elsewhere.

## Working Rules

- Read relevant files before editing, especially `README.md`, `CONTEXT.md`, existing ADRs, and nearby code.
- Keep changes scoped to the requested task and match the repository's existing style.
- Do not add dependencies, data providers, databases, schedulers, or external services unless the request clearly needs them.
- `docs/xzy/` contains another person's investment-system materials. Do not use or reference its content in analysis unless the user explicitly cites it.
- After any completed file-change batch, create a git commit before the final response. Do not push unless explicitly asked.
- Keep every git commit message to a single short sentence. Do not add a body, trailers, attribution, or co-author tags (for example `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`) or any other tool-generated signature.
- Never store API keys, tokens, cookies, account identifiers, or paid-data credentials in the repository.

## Research And Data Principles

- Separate security-level concepts from company-level concepts. A listed company can have multiple securities, share classes, exchanges, or identifiers.
- Separate business-quality screening from valuation. A company can enter a watchlist because of durable business advantages even when its current price is unattractive.
- Preserve source provenance for market and fundamental data: provider, retrieval time, raw identifier, reporting period, currency, exchange, and adjustment policy where applicable.
- Prefer an auditable data flow: raw source records first, normalized records second, derived signals last.
- Treat corporate actions, dividends, split/bonus events, trading calendars, suspension days, and currency as first-class data concerns for equity analysis.
- For financial reports, distinguish reporting period, forecast/pre-announcement dates, official announcement dates, and the reported financial contents.

## Investment Research Rules

Use the user's personal investment system in `docs/personal-investment-system-v1.zh.md` as the default standard for equity analysis. Apply the rules strictly; the watchlist is intended to be small and high quality.

- For single-company, stock-defence, watchlist, valuation, or position-sizing analysis, use the project-level `stock-analysis` skill. It encodes the required workflow: authoritative evidence first, strategy classification, watchlist decision, valuation assessment, scenario analysis, and position guidance.
- When a user defends a stock thesis, split the defence into factual claims and re-check material facts against company filings, periodic reports, exchange announcements, official investor-relations materials, regulator disclosures, or reputable institutional/professional research. Do not accept the defence only because it sounds plausible.
- Always classify the primary investment strategy before valuation: DCF/cash-flow compounder, cigar-butt undervaluation, GARP growth, supply-chain breakout, fallen champion, monopoly resource, or shareholder-return undervaluation. Use the matching valuation method rather than a generic PE comment.
- For growth and supply-chain breakout stocks, do not over-rely on historical financial metrics. Analyze market space, share gains, pricing, margin path, supply bottlenecks, customer validation, and 2-3 year bear/base/bull scenarios.
- Separate three decisions in equity answers: whether the listed company deserves watchlist attention, whether the current security price is attractive, and what position size or watch action is justified under portfolio rules.
- Apply a "strict entry, wide exit" rule for watchlists. Do not add a company to the core watchlist merely because it is familiar, popular, recently down, or has a plausible story. A company must have a durable reason to deserve continued attention.
- Treat moat durability as the first filter. Ask whether a well-funded new entrant could easily enter the industry, replicate the product, buy traffic/channels/capacity, and erode returns. If yes, high current growth or high margins are likely not durable enough for watchlist inclusion.
- Low-barrier consumer, retail, OEM, commodity processing, simple manufacturing, and traffic-buying businesses should normally be rejected unless they have exceptional brand mindshare, network effects, regulatory/resource constraints, switching costs, cost advantages, or verifiable category dominance.
- Do not classify a company as GARP unless growth is both real and defensible. Growth driven by low barriers, ad spending, channel expansion, temporary margins, export cycles, or easily copied products does not qualify.
- Do not call a stock undervalued just because the price fell. For ordinary non-monopoly businesses, roughly 20x-25x PE is not automatically cheap; it needs durable growth, strong cash conversion, and a clear margin of safety. Otherwise classify it as fairly valued or unproven.
- Distinguish "worth understanding" from "worth watching." Many companies can be researched once and rejected. The watchlist should contain only companies that could plausibly become future holdings under the user's position rules.
- Favor omission when evidence is mixed. If moat, valuation, and future compounding quality are not all compelling, reject or keep outside the watchlist rather than adding a low-conviction observation name.
- For every recommendation, state the primary reason for inclusion or exclusion. If excluding a company, be explicit when the reason is weak moat, easy entry, valuation not cheap enough, poor cash conversion, or insufficient durable growth.

Position discipline for future analysis:

- Core holding candidates must justify 15%-25% position potential under the personal investment system. If a company cannot plausibly support that level after deeper verification, it should not be described as a core candidate.
- Tactical positions are only for strong right-side signals or early verified catalysts, not for loosely tracking weak companies. Do not recommend many small "observation positions" as a substitute for strict watchlist selection.
- Never recommend all-in concentration. Even high-conviction opportunities must respect the user's position limits, industry exposure limits, thesis risk, and liquidity risk.

## Validation

- Run the most targeted useful check after changes: tests, lint, typecheck, build, or a small deterministic data/sample validation.
- If a check depends on network access, paid credentials, or unavailable market-data services, say so clearly and validate the local parts instead.
- Do not claim data coverage or analysis correctness unless it has been verified with reproducible checks.
