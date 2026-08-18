# AShareQuant Agent Instructions

Research and data analysis for listed companies in mainland China and Hong Kong markets.

## Where The Standards Live

- **`docs/000_Ashare_workflow.md`** is the master execution spec for the entire A-share pipeline (quality triage → tiering → valuation pool → rolling post-disclosure updates → daily volume/price scan → daily holdings tracking). The pipeline **ends at buy candidates**: the pretrade gate and the sell scan both retired in v2.05 — whether to buy or sell, and how much, is the user's call. Route through its §0 task-routing table and execute the matching section without asking the user to re-explain the process. **Standards live only in that file.** If one looks wrong, edit it first (§15), then re-run — never override or restate its thresholds elsewhere.
- **`docs/000_personal-investment-system-v1.zh.md`** is the governing standard for investment judgment: strategy classification, valuation/scenario method, and research obligations. **Its behavioural red lines, prohibitions, single-veto list and structural caps were all deleted 2026-08-18** — there is no interception protocol any more; execute instructions and report facts. Account-level constraints are down to two exogenous ones (broker credit line, 130% liquidation line, §4).
- **`docs/Ashare_workflow_open_issues.md`** registers confirmed-but-unfixed defects. Check it before trusting a mechanism it lists.
- For single-company, stock-defence, watchlist, valuation, or position-sizing analysis, use the project-level `stock-analysis` skill.

Treat the latest user request and committed project docs as the source of truth for current priorities. Do not turn transient requirements into reusable skill rules.

## Working Rules

- Read the relevant files before editing — especially `README.md`, `CONTEXT.md`, existing ADRs, and nearby code.
- Keep changes scoped to the request and match the repository's existing style.
- Do not add dependencies, data providers, databases, schedulers, or external services unless the request clearly needs them.
- `docs/xzy/` holds another person's investment-system materials. Do not use or reference it in analysis unless the user explicitly cites it.
- **`000_` filename prefix is reserved for files the user opens and reads directly** — it exists to keep those files sorted to the top. Do not add it to design notes, audits, changelogs, issue registers, or any other agent/program working document. Currently prefixed: `docs/000_Ashare_workflow.md`, `docs/000_personal-investment-system-v1.zh.md`, `data/processed/000_a_share_core_valuation_pool.md`, `000_daily_scan_log.md`.
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

## 机器资源约束（后台/长时作业必读）

本机 **8 GB 物理内存、8 核**。**swap 是 macOS 按需生成的，不是固定值**——2026-08-17 实测为 0，
2026-08-18 实测 `total = 5,120 MB / used = 4,028 MB`。**不要把某一次读数当成常量**，每次起重作业前现读
`sysctl vm.swapusage`。有 swap 时超内存表现为剧烈变慢而非立刻黑屏，但 2026-08-17 那次死机是真的
（当时并发跑了 2 个建带 + 2 个扫描器 × 8 并发 ≈ 20 GB 需求，远超物理内存 + 当时可用 swap）。
以下为硬约束，不得"这次应该没事"地绕开：

| 作业 | 实测峰值 | 规矩 |
| --- | ---: | --- |
| 单个回测进程（`backtest_valuation_strategy.py`） | **1.25 GB** | — |
| 扫描器（`sweep_backtest_configs.py`） | 并发数 × 1.3 GB | **`--workers` 缺省已改 2**；上调前先算 `并发×1.3GB + 其它作业 < 5GB` |
| 全市场建带（`build_historical_valuation_bands.py --all`） | 约 1.5 GB（已改流式写盘；改之前是十几 GB） | 仍属重作业，**独占运行** |
| 六步链 / 逐日状态重建 | 约 1.5-2 GB | 独占运行 |

1. **同一时刻只允许一个重作业**。重作业 = 建带、扫描器、逐日状态重建、六步链、长跑带产物回测。
   要并行只能是「一个重作业 + 若干秒级小命令」。
2. **总预算 5 GB**：给系统与用户自己的程序留 3 GB。任何一次启动前先估算峰值，估不出来就先量
   （`/usr/bin/time -l <命令> 2>&1 | grep "peak memory"`）。
3. **写大文件一律流式**：不得把逐日级数据（百万行以上）先堆成 `list[dict]` 再一次性 `writerows`。
4. 排队跑长作业时用**串行**（一个背景任务里 `A && B && C`），不要开多个背景任务同时跑。
5. 单个建带/重建约 35-40 分钟、单臂 23 起点扫描约 6-10 分钟（`--workers 2`）——按此估时间，
   宁可排队等，也不要为了赶时间并发。

## Validation

Run the most targeted useful check after changes. When a check needs network access, paid credentials, or unavailable market-data services, say so plainly and validate the local parts instead. Do not claim data coverage or analysis correctness without a reproducible check behind it.
