# Separate attention class from quality tier; L5 demotes rather than excludes

## Status

Accepted.

## Context

Two documents defined the L1–L5 quality tiers with conflicting meanings for L4 and L5. The operation workflow (§5.7) treated L5 as "garbage / permanent exclusion", while the authoritative deep-review protocol (§1.6) treated L4 as zero-position watch and L5 as "remove from watchlist". The first-round triage already classifies the full universe into worth-attention, boundary-pending, and garbage, so encoding garbage again as L5 double-encoded the same state and made the final tier ambiguous.

## Decision

Attention class and quality tier are two orthogonal axes.

1. The first round classifies every eligible listed company into an attention class: worth-attention, boundary-pending, or garbage. Garbage is permanent removal from the research pool and is decided only in this round.
2. Quality tier L1–L5 is assigned only to worth-attention companies, on business quality and ignoring price. L1–L4 are keeper tiers (L1 core, L2 quasi-core, L3 tactical, L4 zero-position watch).
3. L5 is not a keeper tier. A worth-attention company judged L5-quality is demoted out of worth-attention into boundary-pending, where it can re-enter review on a future hard trigger. L5 is reversible and is not the same as garbage.

The deep-review protocol §1.6 tier criteria are adopted, with "remove from watchlist" clarified to mean demotion to boundary-pending.

## Implications

1. `quality_tier` is populated only for worth-attention companies; garbage and boundary-pending companies carry an `attention_class` but no tier.
2. A company can leave the watchlist two ways: a permanent garbage decision in the first round, or an L5 quality judgment that demotes it to boundary-pending. Only the latter is reversible.
3. Existing rows that recorded garbage as L5 should be re-expressed as `attention_class = garbage` with no tier.
4. CONTEXT.md is the canonical definition for these terms; the operation workflow and deep-review protocol reference it rather than restating divergent meanings.
