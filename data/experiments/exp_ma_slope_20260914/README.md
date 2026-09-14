# MA slope research, 2026-09-14

Primary comparison: BOTH1 versus the current native BASE. The full Chinese interpretation is in `docs/reports/ma_slope_review_2026-09-14.zh.md`; definitions and five fixed candidates were registered in `preregister.md` before valid results. No production parameters or engine implementation were changed.

`slope.py` uses the entering/leaving price identity and the complete corporate-action calendar, including suspended ex-dates. `engine.py` inserts only this added candidate gate into an isolated copy of the native run function. Existing trend and stop MAs retain the native behavior; their suspension defect is tracked as OI-179. This is a conditional comparison against that baseline, not a claim that the complete MA implementation has been repaired.

Valid jobs: smoke 26672737 and formal 26673031. The initial job 26672532 had a defective added slope calculation and is **invalid**; archived files under `invalid_initial/` must never be used as current results.

From the repository root, with the frozen input sources available:

```bash
python3 data/experiments/exp_ma_slope_20260914/test_slope.py
sbatch --account=tes21035 scripts/slurm/ma_slope_smoke_20260914.sbatch
# Wait for successful smoke and inspect smoke.json before the formal run.
sbatch --account=tes21035 scripts/slurm/ma_slope_20260914.sbatch
# After successful completion:
python3 data/experiments/exp_ma_slope_20260914/validate_extra.py
```

The smoke script freezes production state-subset equivalence and reference hashes, verifies the native anchor, and calculates the old frozen-rank1 signal comparison. The formal script runs six arms at 14 starts in full/A, calculates U (A is reusable for all five arms here), verifies 28 BASE paths against the landed OI-167 reference, calculates current reranked-rank1 signal results, and registers 140 candidate rows through the existing ledger writer. Resume only with the same manifest; changed inputs require a new research batch.

The `cache/`, `nav/`, `stats/`, `daily/`, `errors/`, and `signals/` directories hold reproducible path artifacts and are ignored by Git. Inputs reused from the OI-167 frozen directory are identified in `manifest.json`; price files and state files must match those hashes. Compact summaries, paired metrics, observations, interval checks, transactions, attribution, and input/verification manifests are retained in Git.

`extra_verification.json` separately fingerprints the post-run independent validation script. Annual and per-code signal summaries expose composition changes; `signals` and `complete` counts distinguish missing forward windows. Signal return statistics are fixed-horizon gross returns using the prior table's implementation, whereas portfolio summaries use the existing financed execution engine. See the report for these limits and for the exact distinction between filtering a frozen rank1 and reranking eligible candidates.
