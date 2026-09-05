# AShareQuant Agent Instructions

Research and data analysis for listed companies in mainland China and Hong Kong markets.

## Where The Standards Live

- **`docs/000_Ashare_workflow.md`** is the master execution spec for the entire A-share pipeline. Route every pipeline task through its §0 task-routing table and execute the matching section without asking the user to re-explain the process. **Standards live only in that file** — if one looks wrong, edit it first, then re-run. Do not restate its content, thresholds, or section numbers anywhere else, this file included: the doc changes near-daily and restatements have repeatedly gone stale and misled sessions.
- **`docs/000_personal-investment-system-v1.zh.md`** is the governing standard for investment judgment; single-company, stock-defence, watchlist, valuation, and position analysis follow it directly.
- **`docs/Ashare_workflow_open_issues.md`** registers confirmed-but-unfixed defects. Check it before trusting a mechanism it lists. Closed items live in `docs/Ashare_workflow_open_issues_closed.md`; open it only when you need a closed item.
- **`docs/Ashare_backtest_log.md`** and **`docs/Ashare_workflow_changelog.md`** hold only the current epoch (one ≤1.5 KB section per experiment; one line per version). Grep for the section you need instead of reading them whole; older epochs are in `docs/archive/`. Experiment evidence goes to `data/experiments/<exp>/`, the scan ledger is `data/backtest/scan_summaries.csv`.
- **`CONTEXT.md`** holds the stable domain vocabulary; **`docs/adr/`** holds architectural decisions.

Treat the latest user request and committed project docs as the source of truth for current priorities.

## Working Rules

- Read the relevant files before editing — especially `README.md`, `CONTEXT.md`, existing ADRs, and nearby code.
- **`docs/000_Ashare_workflow.md` and `docs/000_personal-investment-system-v1.zh.md` are execution-only（用户多次强调）**: write only what to do — commands, thresholds, procedures, file paths. Never add rationale/motivation（"因为/否则/这保证"）, judgment cases（判例）, version/date/ruling provenance（"（v4.xx，用户 YYYY-MM-DD 裁定）"）, superseded-behavior comparisons（"v4.xx 前…已对齐"）, rejected alternatives, or measured snapshots. That content goes to the changelog, backtest log, open-issues register, or decision log instead. Deleted/retired mechanisms leave no tombstone text — history lives in the changelog, `docs/archive/`, and logs. Before committing any edit to these files, grep the added lines for 判例／裁定／指令／此前／旧口径／已于／已删除／已失效／实测／v4./v1.1 and strip every hit.
- Keep changes scoped to the request and match the repository's existing style.
- Do not add dependencies, data providers, databases, schedulers, or external services unless the request clearly needs them.
- `docs/xzy/` holds another person's investment-system materials. Do not use or reference it in analysis unless the user explicitly cites it.
- **`000_` filename prefix is reserved for files the user opens and reads directly** — it exists to keep those files sorted to the top. Do not add it to design notes, audits, changelogs, issue registers, or any other agent/program working document. Currently prefixed (all in `docs/`): `000_Ashare_workflow.md`, `000_personal-investment-system-v1.zh.md`, `000_a_share_core_valuation_pool.md`, `000_daily_scan_log.md`.
- After any completed file-change batch, create a git commit before the final response. Do not push unless explicitly asked.
- Git commit messages: one short sentence. No body, trailers, attribution, co-author tags, or any tool-generated signature.
- Never store API keys, tokens, cookies, account identifiers, or paid-data credentials in the repository.

## 时区：本机不是北京时间

**本机时钟是欧洲时区（阿姆斯特丹，CEST = UTC+2，冬令时 CET = UTC+1），A 股的一切时点判断都必须换算到北京时间（UTC+8）。**
夏令时期间北京 = 本机 + 6 小时。`date` 直接读出来的是本机时间，**不要拿它判断是否收盘**——
判例：2026-08-18 本机 09:49 被误读成"A 股还在交易"，实际北京已是 15:49、早已收盘。

判断收盘、报告期截止日、`--as-of` 取值、扫描是否可执行，一律用：

```bash
TZ=Asia/Shanghai date '+%Y-%m-%d %H:%M:%S %Z'
```

A 股交易时段（北京）：09:30-11:30、13:00-15:00。`--as-of` 用北京日期，不是本机日期
（本机在 UTC+2 时，北京时间 00:00-06:00 对应本机前一天 18:00-24:00，**跨日**）。

## 机器资源约束与作业提交（后台/长时作业必读）

本机是 Snellius（SURF）的交互节点，**不是**跑重作业的地方（`nproc` 现读，当前 session 为 1 核）。
计算资源一律按 SLURM 作业申请：账户 `tes21035`，缺省分区 `rome`（128 核 / 224 GB / 每核 1792 MiB / 时限上限 5 天）。
`/gpfs/work1/0/qt15419/zwang/mm_quant/RayKey` 与 `/home/zwang/project/mm_quant/RayKey` 是同一份（`/home/zwang/project` 是软链），不要当成两个副本互相同步。

### 耗时任务一律提交 sbatch

**预计超过 10 分钟、或需要多进程并发、或峰值内存超过当前 session 配额的作业，必须写成 sbatch 脚本提交，
不得在交互 session 里前台或后台直接跑。** 交互 session 只留给分钟级的读表、核对、单票查询。

sbatch 脚本放 `scripts/slurm/`（入库），日志写 `logs/`（不入库，只保留 14 天：提交新作业前先跑 `find logs -type f -mtime +14 -delete`）。模板：

```bash
#!/bin/bash
#SBATCH -J <作业名>
#SBATCH -p rome
#SBATCH -n 16                 # 见下「申请多少」
#SBATCH -t 02:00:00           # 按实测耗时留 3 倍余量；超时直接被杀，产物丢失
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/<script>.py <args>
```

`scripts/*.py` 是纯标准库，**不需要 `module load`**；`sbatch` 缺省 `--export=ALL`，`python3` 直接解析到 `~/miniconda3`（3.11.8）。
计算节点可访问外网，§8 每日扫描也可以在批处理里跑。

```bash
sbatch scripts/slurm/<name>.sbatch                              # 提交
sbatch --test-only scripts/slurm/<name>.sbatch                  # 只校验＋预估计费，不真提交
squeue -u $USER                                                 # 排队/运行
sacct -j <id> --format=JobID,State,Elapsed,MaxRSS,AllocCPUS     # 结束后读实际耗时与峰值内存
scancel <id>
```

**提交后不要空转轮询等结果**：记下 job id 转做别的事，靠 `sacct` 的 State 与日志尾部确认结束，再读产物。

### 申请多少

`-n` 同时决定核数与内存（每核 1792 MiB）。**rome 计费按 16 核向上取整**——`-n 1` 与 `-n 16` 计费相同，
所以下限就是 `-n 16`（= 28 GB）；用 `--mem` 要超过 `核数 × 1792 MiB` 时，计费改按内存折算，同样取整到 16 的倍数。

| 作业 | 单进程峰值内存 | 本机实测耗时 | 申请 |
| --- | ---: | ---: | --- |
| 单个回测进程（`backtest_valuation_strategy.py`，23 起点中的一个） | 1.49 GB（读候选侧＋持仓侧两份状态文件；只读一份时 1.25 GB） | 待测 | `-n 16` |
| 扫描器（`sweep_backtest_configs.py --workers N`） | N × 1.49 GB | 待测 | `-n N`，N 取 16/32/48…（`-n 32` 给 56 GB，够 32 并发的 47.7 GB） |
| 全市场建带（`build_historical_valuation_bands.py --all`，§6.7 第 2 步） | 2.6 GB | **8 分 05 秒** | `-n 16` |
| B2 建带（第 2b 步，与第 2 步串行） | 同上 | **7 分 29 秒** | `-n 16` |
| 银行股利折现覆盖（`rebuild_bank_bands.py`，第 3 步，每侧一次） | 0.06 GB | **2 分 45 秒** | `-n 16` |
| 合成持仓侧逐日状态（`build_hold_daily_states.py`，归并两份 2.1 GB） | ≤ 0.1 GB | **2 分 32 秒** | `-n 16` |
| 六步链其余各步 | ≤ 建带 | 分钟级 | `-n 16` |

§6.7 第 2→3 步全链约 **23 分钟**；逐日状态文件每份 2.1 GB、持仓侧 2.2 GB。
**纯 Python 单线程，rome 单核比原 Mac 慢约 3 倍**（建带 2.5 分 → 8 分），换更多核不会让单个进程变快，
只有并发跑多臂才吃得到核数。峰值内存由代码决定、跨机器不变；新作业的耗时先小样本跑一次，
`sacct -j <id> --format=Elapsed,MaxRSS` 读实际值，再定 `-t` 与并发数。

1. `--workers` 按申请到的核数设，单节点上限 128。
2. **写大文件一律流式**：不得把逐日级数据（百万行以上）先堆成 `list[dict]` 再一次性 `writerows`。
3. 回测 A/B 优先用**面板子集状态文件**（只含 v6b 宇宙代码；回测只读宇宙内代码，已证与全市场文件逐位等价，
   回测日志 §12.94.6）；`BASE` 正式读数仍按 `sweep_backtest_configs.py` 的全市场文件。
4. `data/raw/ohlcv/` 的行情历史库由 `fetch_ohlcv_history.py` 按需增量，**不随 §8 每日扫描更新**；
   全量重建或长跑前先确认末行日期，否则"期末"不是你以为的日期。

## Validation

Run the most targeted useful check after changes. When a check needs network access, paid credentials, or unavailable market-data services, say so plainly and validate the local parts instead. Do not claim data coverage or analysis correctness without a reproducible check behind it.
