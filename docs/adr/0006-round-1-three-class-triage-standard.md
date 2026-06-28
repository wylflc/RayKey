# Define the round-1 three-class triage standard

## Status

Accepted.

## Context

Round-1 triage assigns every A-share an attention class (worth_attention / boundary_pending / garbage) before any L1–L5 tiering. The earlier §5.4 wording let "no moat / homogeneous" and "low-barrier business" send a company to garbage, which ADR-0005 makes a permanent, never-re-reviewed exclusion. That conflated company-level current weakness with permanent structural exclusion, and the worth_attention bar ("some degree of moat") was too loose for a watchlist that had grown to roughly 1000 names.

## Decision

1. **Per-company independence**: each company is judged on its own; no single metric may batch-classify many companies. Peer context is an input, not a shortcut.
2. **Competitiveness over price/profit/market cap**: classification is based on durable competitiveness. Price action, theme heat, profit, and market cap are evidence for neither inclusion nor exclusion.
3. **worth_attention is strict and gated by the capital-replicability test**: the advantage must be durable enough that a well-funded entrant cannot quickly replicate it and erode returns. There is no numeric target; the count follows from the standard.
4. **garbage is narrow and permanent — only** governance/fraud disasters or structurally hopeless low-barrier industries where no company can build a durable advantage. Company-level current weakness in a non-hopeless industry goes to boundary_pending, which is reversible.
5. **boundary_pending covers two cases**: insufficient reliable evidence to judge (including new listings without an annual report), or judgeable-but-currently-weak in a non-hopeless industry. It is re-reviewed when reliable evidence appears or a hard trigger occurs.
6. **Round-1 is a light triage**: business model + obvious durable advantage or its absence + obvious negatives. It does not require reading each annual report; obvious garbage can be decided quickly. Deep annual-report and research reading is deferred to L1–L5 tiering and the authoritative deep review.

## Implications

1. The standard is recorded in operation-workflow §5.4; CONTEXT.md defines the terms; this ADR records the decisions and trade-offs.
2. Re-running round-1 over the full universe will shrink worth_attention well below the prior ~1000 and move most merely-mediocre companies to reversible boundary_pending rather than permanent garbage.
3. The 421 securities temporarily reclassified from L5 to boundary_pending (see the decision log) are re-judged under this standard during the full rescan.
4. "Comprehensively dominated by a stronger peer" is a tiering / peer-calibration consideration, not a round-1 garbage trigger.
