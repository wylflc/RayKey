# 归档：已结束轮次的产物与旧纪元日志

不是任何现行流程的输入；现行真值只在 `data/processed/`。

| 条目 | 内容 | 来源与说明 |
| --- | --- | --- |
| `decision_log_2026-06-14_to_2026-08-30.csv` | 决策日志旧纪元行（43,369 行） | 自 `data/processed/a_share_workflow_decision_log.csv` 移出；`build_a_share_company_analysis_index.py` 同读 |
| `daily_scan_log_2026-07-10_to_2026-08-10.md` | 旧账户纪元每日扫描日志 | 自扫描日志移出 |
| `daily_scan_log_2026-08-13_to_2026-08-30.md` | v2.90~v4.99 每日扫描日志 | 自 `docs/000_daily_scan_log.md` 移出 |
| `pretrade_decisions_2026-08-03.csv` | v2.05 退役的买前裁决记录 | 只作历史 |
| `a_share_company_profiles.csv` | 早期聚合站公司简介（16.7 MB） | 生产脚本已退役；只有 `scripts/experimental/` 的旧校准实验引用 |
| `financials_original/` | 新浪原始披露口径逐期财务（111 文件） | 只有 `scripts/archive/fetch_sina_original_financials.py`／`build_judgment_input.py` 引用 |
| `full_market_screen/` | OI-036 全市场重筛队列与判定档（`screen_queue.csv`、`verdicts.csv`、`final_watchlist.csv`） | 该轮 2026-08-31 收口；脚本 `scripts/archive/build_full_market_screen_queue.py` |
| `pit-judgment-2026-08/` | 时点关注度判定中间产物与面板世系 | 见目录 README |
| `completed-queues/` | 已跑完的工作队列与复核记录 | 见目录 README |
| `model-blind-trial-2026-08-30/` | 判定模型三轮对照材料 | 见目录 README |
| `2026-06-two-layer-review/` | 2026-06 两层复核轮最终产物 | — |
| `quality-scores-v2/` | v2 质量分快照 | — |
