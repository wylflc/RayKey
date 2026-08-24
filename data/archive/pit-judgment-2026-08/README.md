# 归档：时点关注度判定（2026-08-08 ~ 08-21）的中间产物与面板世系

回测宇宙的现行真值只有 `data/processed/pit_attention/` 里的 **`panel_moat_bank_v6b.csv`**（装配脚本 `scripts/build_moat_panel.py`，
基座 `panel_moat_bank_v5.csv` ＋ 判定覆盖 `verdicts_pit_moat_v6.csv`，锚点册 `anchors_v6.csv`），以及判定源
`judgment_log.csv`／`judgment_log_delisted_rejudge.csv`／`exit_log.csv`／`verdicts_report_level.csv`。
本目录存放通往它的全部中间版本与队列，**不是任何现行流程的输入**；执行口径见 `docs/archive/Ashare_pit_judgment_protocol.md`，
过程与结论见 `docs/Ashare_backtest_log.md` §12.25、§12.32~§12.34、§12.51~§12.54、§12.71、§12.106。

| 组 | 文件 | 来源 |
| --- | --- | --- |
| 粗筛候选（OI-034 第 4 步） | `candidates_2005/2010/2015/2020.csv` | `scripts/archive/build_pit_attention_candidates.py` |
| 逐年名单第一代（OI-034 第 6 步） | `universe_wa*.csv`、`entry_overrides.csv`、`setb_intervals.csv`、`verdicts_2010/2015/2020.csv` | `scripts/archive/build_pit_attention_yearly.py` |
| 面板式判定（OI-034 第 7 步） | `verdicts_panel.csv`、`panel_queue.csv`、`universe_panel_*.csv`、`pit_universe*.csv`、`universe_live261.csv` | `scripts/archive/pit_panel.py` |
| 逐报告期判定协议的队列 | `judgment_queue.csv`、`bloom_queue.csv`、`recheck_queue.csv`、`restatement_contamination.csv`、`f10_org_profile.json` | `scripts/archive/build_judgment_input.py`（判定输入文本 `judgment_input_*.txt` 可由它重建，已不入库） |
| 护城河名单世系 | `verdicts_pit_moat.csv` → `_v2` → `_v3_restored`（现行 `verdicts_pit_moat_v6.csv` 留在原目录） | §12.32~§12.34、§12.51~§12.52 |
| 面板世系 | `panel_moat_bank_restored/v2/v3/v4.csv`（v5 由 `scripts/archive/fix_panel_entry_lookahead.py` 自 v4 生成，留在原目录） | §12.53~§12.54 |
| 质量组实验 | `quality_quota_top20.csv` | `scripts/experimental/build_quality_quota.py`（§12.60，不采纳） |

各实验脚本的缺省路径已改指本目录；重跑历史实验时直接引用即可。
