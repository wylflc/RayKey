# 判定模型三轮对照（OI-036 C 层 251 家，2026-08-30）

同一批 251 家、同一份判定说明、同一批事实列，跑三轮：

| 文件 | 轮次 | 模型 | 隔离条件 |
| --- | --- | --- | --- |
| `round1_sonnet.jsonl` | 首轮 | claude-sonnet-5 | 无（正常执行） |
| `round2_opus_informed.jsonl` | 知情复判 | claude-opus-5 | 只禁读 `out_*.jsonl`；`verdicts.csv`／三类表已含首轮结论，两个子代理报告读到过 |
| `round3_opus_blind.jsonl` | 双盲复判 | claude-opus-5 | 在 `ac894d09`（本轮判定开始前的提交）开 git worktree，agent 只能读该树，主仓库路径禁访问；九批全部报告未破 |

`compare.py` 复现全部对照数字（路径为当时的 scratchpad，重跑时改成本目录）。

结论：**三方类别 251/251 完全一致**（250 boundary_pending、1 worth_attention），无升类、无 garbage、`never_admit` 全 0。
排队层建议知情/双盲 251/251 一致。参考分双盲对知情平均绝对差 2.5 分、完全相同 104 家。
落盘的是 round2（`verdicts.csv` 相应行 `judged_by_model=claude-opus-5`）。
