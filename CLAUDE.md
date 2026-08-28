# AShareQuant Agent Instructions

Research and data analysis for listed companies in mainland China and Hong Kong markets.

## Where The Standards Live

- **`docs/000_Ashare_workflow.md`** is the master execution spec for the entire A-share pipeline. Route every pipeline task through its §0 task-routing table and execute the matching section without asking the user to re-explain the process. **Standards live only in that file** — if one looks wrong, edit it first, then re-run. Do not restate its content, thresholds, or section numbers anywhere else, this file included: the doc changes near-daily and restatements have repeatedly gone stale and misled sessions.
- **`docs/000_personal-investment-system-v1.zh.md`** is the governing standard for investment judgment; single-company, stock-defence, watchlist, valuation, and position analysis follow it directly.
- **`docs/Ashare_workflow_open_issues.md`** registers confirmed-but-unfixed defects. Check it before trusting a mechanism it lists.
- **`CONTEXT.md`** holds the stable domain vocabulary; **`docs/adr/`** holds architectural decisions.

Treat the latest user request and committed project docs as the source of truth for current priorities.

## Working Rules

- Read the relevant files before editing — especially `README.md`, `CONTEXT.md`, existing ADRs, and nearby code.
- **`docs/000_Ashare_workflow.md` and `docs/000_personal-investment-system-v1.zh.md` are execution-only（用户多次强调）**: write only what to do — commands, thresholds, procedures, file paths. Never add rationale/motivation（"因为/否则/这保证"）, judgment cases（判例）, version/date/ruling provenance（"（v4.xx，用户 YYYY-MM-DD 裁定）"）, superseded-behavior comparisons（"v4.xx 前…已对齐"）, rejected alternatives, or measured snapshots. That content goes to the changelog, backtest log, open-issues register, or decision log instead. Deleted/retired mechanisms leave no tombstone text — history lives in the changelog, `docs/archive/`, and logs. Before committing any edit to these files, grep the added lines for 判例／裁定／指令／此前／旧口径／已于／已删除／已失效／实测／v4./v1.1 and strip every hit.
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
2026-08-18 实测 `total = 5,120 MB / used = 4,028 MB`，2026-08-20/21 一天内 total 在 4,096~6,144 MB 间浮动、
used 2.9~4.9 GB（浏览器独占 ~1 GB）。**不要把某一次读数当成常量**，每次起重作业前现读
`sysctl vm.swapusage`。有 swap 时超内存表现为剧烈变慢而非立刻黑屏，但 2026-08-17 那次死机是真的
（当时并发跑了 2 个建带 + 2 个扫描器 × 8 并发 ≈ 20 GB 需求，远超物理内存 + 当时可用 swap）。
以下为硬约束，不得"这次应该没事"地绕开（峰值为 `/usr/bin/time -l` 的 peak memory footprint，2026-08-21 实测）：

| 作业 | 实测峰值 | 实测耗时 | 规矩 |
| --- | ---: | ---: | --- |
| 单个回测进程（`backtest_valuation_strategy.py`，23 起点中的一个） | **1.49 GB**（v4.92 起读候选侧＋持仓侧两份状态文件，2026-08-28 实测；只读一份时 1.25 GB。全市场或面板子集状态文件都一样，内存由宇宙内代码决定） | 读全市场 2.1 GB 状态文件 ~26 s／份，两份 ~52 s；读面板子集文件 ~6 s | — |
| 扫描器（`sweep_backtest_configs.py`） | 并发数 × 1.49 GB | 单臂 23 起点：面板子集文件 ~1.5 分钟、全市场文件 ~5 分钟（2 并发时读文件相互争用）；**与建带/物化链并发且 swap 已用 ≥3.5 GB 时实测放慢到 ~60 分钟（2026-08-23）**，长作业仍应串行 | **`--workers` 缺省 2**；上调前先算 `并发×1.49GB + 其它作业 ≤ 5GB` |
| 全市场建带（`build_historical_valuation_bands.py --all`，5,572 只、1,522 万行逐日状态） | **2.3 GB**（RSS 1.7 GB；流式写盘后的实测，此前文档写的 1.5 GB 偏低） | **~2.5 分钟**（此前写的 35-40 分钟早已过期） | 重作业 |
| 银行股利折现覆盖（`rebuild_bank_bands.py`） | 0.06 GB | ~2 分钟 | 轻作业 |
| 六步链其余各步 | ≤ 建带 | 分钟级 | — |

1. **并发按实测峰值加总，总预算 5 GB**（给系统与用户自己的程序留 3 GB）。已实跑无事的组合：
   建带 `--all`（2.3 GB）＋ 1 个回测进程（1.49 GB）＝ 3.8 GB；2 并发扫描（3.0 GB）＋ 若干只读大文件的轻脚本。
   **不得**：两个建带（§6.7 第 2 步与第 2b 步 B2 建带串行）；2 并发扫描 ＋ 建带（5.3 GB 超线）；任何 `--workers ≥ 3` 的扫描叠加别的重作业。
   峰值估不出来就先量（`/usr/bin/time -l <命令> 2>&1 | grep "peak memory"`）。
2. **写大文件一律流式**：不得把逐日级数据（百万行以上）先堆成 `list[dict]` 再一次性 `writerows`。
3. 排队跑长作业时用**串行**（一个背景任务里 `A && B && C`），不要开多个背景任务同时跑。
4. 回测 A/B 优先用**面板子集状态文件**（只含 v6b 宇宙代码；回测只读宇宙内代码，已证与全市场文件逐位等价，
   回测日志 §12.94.6）——快 4 倍、少争用；`BASE` 正式读数仍按 `sweep_backtest_configs.py` 的全市场文件。
5. `data/raw/ohlcv/` 的行情历史库由 `fetch_ohlcv_history.py` 按需增量，**不随 §8 每日扫描更新**（2026-08-21 核对全库停在
   08-07）；全量重建或长跑前先确认末行日期，否则"期末"不是你以为的日期。

## Validation

Run the most targeted useful check after changes. When a check needs network access, paid credentials, or unavailable market-data services, say so plainly and validate the local parts instead. Do not claim data coverage or analysis correctness without a reproducible check behind it.
