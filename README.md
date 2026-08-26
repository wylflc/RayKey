# AShareQuant

A 股上市公司研究与数据分析仓库（附带港/美/韩观察清单）。核心是一条可复现的五阶段研究流水线：全市场三类初筛与质量分层 → 对 `worth_attention` 建模型估值带 → 披露与事件滚动复核 → 每日行情/估值/相关性扫描 → 执行清单与持仓跟踪。所有结论写入决策日志可审计。

## 两份唯一标准

- **`docs/000_Ashare_workflow.md`** — A 股流水线的执行规范（唯一真值）。§0 任务路由表把每类请求映射到章节与脚本；本 README 不复写任何参数或命令链。
- **`docs/000_personal-investment-system-v1.zh.md`** — 个人投资规则手册（账户级规则、策略分类、研究纪律）。买卖机制只认工作流 §9.3。

配套文档：

- `docs/Ashare_quality_rubric.md` — §5.7 分层的打分细则与判例（在用细则）。
- `docs/Ashare_workflow_changelog.md` — 逐版规则变化；`docs/Ashare_backtest_log.md` — 全部回测实验与历代读数（工作流 §12 只留现行口径）。
- `docs/Ashare_workflow_open_issues.md` — 已确认未修的缺陷与待办（含一行式已结案索引）。
- `docs/Ashare_quant_exp1_index_universe.md`／`exp2_volume_price.md` — 两个研究性实验（无选股宇宙、纯量价），追加式记录。
- `docs/adr/` — 架构决策；`CONTEXT.md` — 稳定领域词汇；`CLAUDE.md` — 代理工作规则（`AGENTS.md` 是指针）。
- `docs/peer-group-calibration/` — §5.4 引用的逐行业校准证据。
- `docs/archive/` — 已完成的过程记录、已实施的设计、已归档的时点判定协议。旧正文全文快照不入库，用 `git show <提交>:<路径>` 取回。

## 目录结构

- `data/raw/` — 不可变名单快照（ADR-0001）与原始数据。行情/逐季财务/三大报表/研报为 `.gitignore` 抓取产物，由各 `fetch_*` 脚本按需重建。
- `data/interim/` — 活跃队列与取证中间件（报告更新队列、估值证据、建带卡等）。
- `data/processed/` — 现行产物与唯一真值表（三类表、分层表、档案表、生产带、核心池、持仓、决策日志）；`pit_attention/` 只保留回测宇宙的现行世系（`panel_moat_bank_v6b.csv` 及其判定源）。
- `data/companies/<代码>_<名称>/` — 逐票研究目录：`README.md`（档案渲染件）＋部分早期 `fundamentals.md`/`research_ledger.md` 台账。
- `data/archive/` — 已结束轮次的产物：`pit-judgment-2026-08/`（时点判定中间产物与面板世系）、`completed-queues/`、`2026-06-two-layer-review/`、旧纪元每日扫描日志等，各目录有 README。
- `scripts/` — 确定性流水线脚本（公司判断是模型作业，不在脚本里设阈值，ADR-0004/0006）。
- `scripts/experimental/` — 已出结论的实验代码（README 索引到回测日志各节）；`scripts/archive/` — 退役脚本（三个月后可永久删除，见其 README 表）。
- `notebooks/` — 诊断可视化（估值带 vs 股价、买卖点通道）。

**派生产物皆可重建、不入库**：逐日估值状态、ROIC 带、回测原件由 `scripts/clean_derived_artifacts.py` 统一清理（缺省只报告，`--apply` 才删）；历次扫描读数归并在 `data/processed/backtest/scan_summaries.csv`。参数扫描一律走 `scripts/sweep_backtest_configs.py`（`BASE` 即 §9.3.1.2 基准，不手抄命令）。

## 常用入口

```bash
python3 scripts/fetch_a_share_universe.py --output data/raw/a_share_securities.csv   # 名单刷新（§5.3）
python3 scripts/build_quarterly_quality_review_queue.py --as-of YYYY-MM-DD           # 季度审查队列
python3 scripts/build_report_update_queue.py --market A_SHARE --signal-date YYYY-MM-DD     # 披露更新队列
python3 scripts/build_a_share_company_analysis_index.py                              # 跨轮次公司结论索引
```

估值重建、每日扫描、持仓跟踪与回测的完整命令链只在工作流 §6.7、§8.2、§9.1、§11、§12——不在此复写，避免第二份口径漂移。`scripts/workflow_decision_log.py` 从工作流首行解析版本号供全部脚本写日志。

## 已关闭的路线（防止误用）

- **港股/美股全覆盖打分管线**（v2.00 退役）：脚本在 `scripts/archive/`，口径 `docs/archive/moat-scoring-rubric.md`。海外覆盖只走工作流 §6.8 点名清单（ROIC 口径由三表重算），产物 `data/processed/overseas_watchlist_valuation.csv`，永不可买。
- **通用逐类建带公式 / PEG 带 / 买前闸门 / 三态矩阵**等退役机制：历史见 changelog 与 `docs/archive/`，代码残留只作遗留行校验（`validate_valuation_bands.py`）。
- **2026-06 两层复核轮**（已闭）：最终产物在 `data/archive/2026-06-two-layer-review/`；跨轮结论用上面的公司分析索引合并读取。

## 原则

- 原始 → 中间 → 产物分层存放；保留数据出处（来源、抓取时间、口径、复权策略）。
- 上市公司 ≠ 证券；关注名单是研究产物不是买入清单；质量判断与估值判断分离。
- 公司级结论逐家判定，不由阈值批量决定（ADR-0004）。
- 不提交任何凭据、Cookie、付费数据访问细节或私人账户标识。

## 开发约定

改动前先读相关文档与就近代码；改动后跑最相关的检查（`scripts/test_*.py`）；完成一批改动即提交，不主动 push。
