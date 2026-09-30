# 长跑持仓延至 2026-09-29 与亏损持仓的退出路径（描述统计）

回测日志 §12.291。在册行情多止于 08-07（141 只到 08-28），本目录把回测宇宙与全部银行保险的行情续到 09-29，
重建状态后用现行 `BASE`（S15）与 v4.221 `BASE`（OLD）各 14 起点长跑。`data/raw/ohlcv/`、`data/processed/` 未写。

```bash
sbatch --account=tes21035 scripts/slurm/longrun_now.sbatch   # fetch → build → validate → run（作业 27385420，15 分钟，峰值 21 GB）
python3 analyze.py                                            # 交互节点，约 30 秒
```

| 文件 | 内容 |
| --- | --- |
| `fetch_report.json` | 逐票续取行数；重叠旧行开高低收逐根核对（0 处不一致） |
| `validation.json` | 重建状态对 OI-230 DC 子集逐行核对：08-07 及以前 965,941 行一致、3 行不同（旧日历末日提前一日用中报带） |
| `holdings.json` | 两个长跑锚点 09-29 持仓、9 月流水、14 起点持仓汇总 |
| `exits.json` | 曾浮亏 ≥ 20% 的周期按退出方式汇总（跨起点同票同出场日去重），海螺水泥与中材国际逐起点周期 |
| `exits_cases.csv` | 28 条路径的全部持有段：入出场、最深浮亏、最大权重、退出方式、周期收益 |

`ohlcv/`、`states/`、`runs/` 不入库，重跑即得。
