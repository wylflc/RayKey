# Separate attention class from quality tier

## Status

Accepted. Revised 2026-08-03: the L1–L5 tier scale this ADR originally carried was retired
by workflow v1.27 (three tiers, L1–L3) and its L5-demotion rule was repealed outright. Those
clauses are deleted rather than kept as history — they read as if in force and contradicted
the current standard. The orthogonality decision below is unaffected and remains in force.

Amended 2026-08-24 (workflow v4.21 added the `documented_not_attention` class and the L4
tier): a tier is no longer assigned *only* to worth-attention companies — a
documented-not-attention company carries L4. The orthogonality still holds: L4 is the tier
that accompanies that attention class, it does not create it. An L3→L4 change is an
`attention_class` migration decided on its own evidence (workflow §5.5), never a rating
outcome. Boundary-pending and garbage companies still carry no tier.

## Context

Two documents defined quality tiers with conflicting meanings, and one of them used the tier
scale to encode "not worth watching" — a state the first-round triage already encodes as an
attention class. Encoding the same state twice made the final tier ambiguous: a reader could
not tell whether a tier described business quality or pool membership.

## Decision

Attention class and quality tier are two orthogonal axes.

1. Every eligible listed company carries an attention class: worth-attention,
   boundary-pending, or garbage. **Pool membership is decided on this axis and only on this
   axis** — first in round-1 triage, thereafter only by the state migrations the workflow
   permits (§5.4.7).
2. Quality tier is assigned on business quality and ignoring price: L1–L3 for worth-attention
   companies, L4 for documented-not-attention companies. **It sets how strict the buy/hold
   bar is, nothing else.**
3. **The rating process has no power over pool membership.** No quality tier — however low —
   removes a company from worth-attention. A company leaves the pool only by an
   `attention_class` decision (the L4 tier follows that decision, it does not cause it).

## Implications

1. `quality_tier` is populated for worth-attention (L1–L3) and documented-not-attention (L4)
   companies; garbage and boundary-pending companies carry an `attention_class` but no tier.
2. A quality downgrade and a pool removal are separate decisions with separate evidence
   requirements. Neither implies the other.
3. `CONTEXT.md` defines these terms; the workflow references it rather than restating
   divergent meanings.

## Where the current standard lives

The tier scale itself is **not** fixed by this ADR — it lives in `docs/000_Ashare_workflow.md`
§5.7 (currently L1 strong / L2 medium / L3 weak moat) with the scoring detail in §5.7.4 and
`docs/Ashare_quality_rubric.md`. Point 3 above is restated as §5.7.4 评分硬约束 first clause
(「只对 `attention_class = worth_attention` 的公司评分；评级不改变名单归属」). If the two ever
disagree, the workflow wins — per `CLAUDE.md`, standards live only in that file.
