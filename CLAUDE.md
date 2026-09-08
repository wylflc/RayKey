# AShareQuant Agent Instructions

Research and data analysis for listed companies in mainland China, with overseas watchlists and backtest research.

## Standards and task routing

- Start pipeline tasks at the routing table in [docs/000_Ashare_workflow.md](docs/000_Ashare_workflow.md). It governs classification, valuation, execution and backtesting.
- [docs/000_personal-investment-system-v1.zh.md](docs/000_personal-investment-system-v1.zh.md) governs account constraints, research categories and research duties.
- Read relevant entries in [docs/000_Ashare_workflow_open_issues.md](docs/000_Ashare_workflow_open_issues.md) before relying on an affected mechanism. Consult the closed index only when needed.
- Read [README.md](README.md), the relevant standard and nearby code before editing. Current company decisions come from the structured files named in the workflow. Historical reports, calibration notes and archived material are evidence to check, not operating instructions.
- Search the changelog and backtest log for the relevant entry; do not load them in full. Each experiment log entry is at most 1.5 KB and points to its detailed evidence. Each changelog version occupies one row.

Treat the latest user request and current project standards as the source of truth.

## Editing and validation

- Keep the workflow and investment system execution-only: commands, thresholds, procedures and paths. Put rationale, cases, version comparisons and measured results in logs or reports. Keep version metadata in the title only. Recover old text from Git; do not create full-document historical copies.
- Define each rule in one place. Change that standard before its implementation; other documents link to it instead of copying thresholds. Run `python3 scripts/audit_repository_docs.py` after instruction or document changes.
- Keep changes scoped. Do not add dependencies, providers, databases, schedulers or services unless the task needs them.
- `docs/xzy/` contains another person's materials. Do not read, use or edit it unless the user explicitly cites it.
- Reserve the `000_` filename prefix for documents the user opens directly.
- Never store credentials, tokens, cookies, account identifiers or paid-data access details in the repository.
- Run the most targeted useful checks. State network, credential and data limitations; do not claim validation beyond reproducible evidence.
- Commit each completed change batch before the final response. Use one short sentence, without a body or attribution. Do not push unless asked.

## Dates

Use Beijing time for every A-share signal date, reporting cutoff and market-session check:

```bash
TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z'
```

## Compute resources

This is a Snellius interactive session. `/gpfs/work1/0/qt15419/zwang/mm_quant/RayKey` and `/home/zwang/project/mm_quant/RayKey` resolve to the same repository.

- Submit work expected to exceed 10 minutes, use multiple processes or exceed session memory through SLURM. Keep interactive work to short inspections and single-company queries.
- Put jobs in `scripts/slurm/`, logs in `logs/`. Before submission, delete log files older than 14 days with `find logs -type f -mtime +14 -delete`.
- Use account `tes21035`, partition `rome`. Request at least 16 CPUs, in multiples of 16; budget 1792 MiB per CPU and at most 128 CPUs per node. Keep `--workers` within the allocation.
- Read prior resource measurements from job accounting; measure unfamiliar work on a small sample. Set the time limit with headroom and check peak memory with `sacct`.
- Stream large data files. Do not accumulate millions of rows in `list[dict]` before writing.
- Check source price-history end dates before rebuilding or backtesting. Daily scans do not refresh the historical price cache.
- Use panel-subset states for A/B runs only when equivalence to the required universe has been verified. Formal baseline inputs come from `sweep_backtest_configs.py`.

```bash
sbatch --test-only scripts/slurm/<name>.sbatch
sbatch --account=tes21035 scripts/slurm/<name>.sbatch
sbatch --account=tes21035 --export=ALL,VAR=value scripts/slurm/<name>.sbatch
squeue -u "$USER"
sacct -j <id> --format=JobID,State,Elapsed,MaxRSS,AllocCPUS
```

Pass job environment variables through `--export`. After submission, record the job ID and continue other work; check completion before consuming outputs.
