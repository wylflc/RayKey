# 目录精简与文件索引审核

审核日期：2026-09-05。审核对象：`f2a5d837^..7adbcf1e`，包括目录迁移、日志压缩与归档、扫描台账拆分。工作区开始审核时干净。本次交付审核记录与待修登记，尚未修改实现。

结论：**不能认定所有入口均可运行。** 在用脚本的本地回归与主要命令行入口通过，但确认 4 项迁移遗漏：实验配置仍引用旧目录、旧实验报告会重新混入旧计量口径、核心池档案链接失效、退役脚本迁移后无法导入。它们分别登记为 OI-152～OI-155。

## 已确认问题

### OI-152｜P2：实验配置内的路径没有随目录迁移

16 个可执行配置文件仍包含 304 处 `data/processed/experiments/` 路径，全部指向不存在的旧位置。其中 92 处替换为 `data/experiments/` 后目标已经存在；其余目标还涉及输出目录或需重建的派生产物，不能仅凭路径替换就声称能完整复跑。

具体例子：`data/experiments/exp_a/configs/aligned_arms.txt:2` 的 `--universe-file` 仍为 `data/processed/experiments/universes/cap_top300_s50.csv`。调用实际引擎的 `load_universe()` 会抛出 `FileNotFoundError`；读取迁移后的同名文件正常，得到 62 个成员变更日期。

受影响配置：

- `exp_a/configs/`：`aligned_arms.txt`、`aligned_lines.txt`、`no_leverage.txt`、`nolev_arms.txt`、`prod_arms_a.txt`、`prod_arms_b2.txt`、`prod_lines.txt`。
- `exp_oi115_trailleg/configs/trail_arms.txt`。
- `exp_reaudit_minority/configs/`：`combo_c1.txt`、`guard_decomp.txt`、`guardeff_margin.txt`、`u_guardeff.txt`、`u_troughoff.txt`、`val_revert.txt`。
- `exp_sb1_daily_buys/configs.txt`、`exp_trough_guard_review/configs.txt`。

上述路径均相对于 `data/experiments/`。其中组合臂、谷底守卫及 trailleg 配置仍被 `scripts/slurm/oi140_combo_c1.sbatch`、`reaudit_minority_followup.sbatch`、`oi123_resweep14.sbatch` 等作业读取；只更新 sbatch 中的 `EXP` 并不能修复配置内部路径。修复时应区分可执行配置与历史运行日志，避免改写历史证据。

### OI-153｜P2：台账拆分没有覆盖全部写入入口

现行 `data/backtest/scan_summaries.csv` 确实只有 140 行 m2，但 `scripts/clean_derived_artifacts.py:122` 的 `merge_summaries()` 仍无条件接收全部计量版本。

`scripts/experimental/sb1_daily_buys_evidence.py:70` 和 `trough_guard_evidence.py:94` 继续将 m1 摘要合并并覆写现行台账。这两条写入路径也未调用新增的 `build_arms_index()`。使用现有 SB1 的 420 个摘要文件进行**只读合并模拟**，返回 560 行，其中 m2 为 140 行、m1 为 420 行；真实台账在审核期间仍保持 140 行，没有执行覆写。

影响：重出旧实验报告便会破坏“现行台账只含 m2”的约定；以后新增摘要还可能使按臂索引未及时更新。应统一台账写入接口，按计量版本分流，并在实际更新后重建索引，同时保留已有历史记录。

### OI-154｜P2：核心池阅读版的 10 个档案链接失效

`scripts/build_a_share_core_valuation_pool.py:49` 已将阅读版移到 `docs/`，但第 414 行仍生成 `../companies/<目录>/README.md`。这个相对路径只在旧的 `data/processed/` 位置成立。

现有 `docs/000_a_share_core_valuation_pool.md:239` 起的 10 个 L4 公司链接全部失效。修复生成器后还需要刷新阅读版；仅手改 Markdown 会在下次生成时复发。建议根据输出 Markdown 的所在目录计算相对路径。

### OI-155｜P2：新归档脚本的导入路径与根目录层级未调整

`scripts/archive/build_full_market_screen_queue.py:46` 仍把自身目录加入 `sys.path`，而依赖的 `fetch_a_share_universe.py` 与 `build_historical_valuation_bands.py` 位于上一级 `scripts/`。第 50 行的 `parents[1]` 迁移后也变成 `scripts/`，不再是仓库根目录。

复现命令：`python3 scripts/archive/test_full_market_screen_queue.py`，实际报 `ModuleNotFoundError: No module named 'fetch_a_share_universe'`。即使外部补了 `PYTHONPATH`，数据路径仍会错误地落到 `scripts/data/`。影响范围为该退役流程的复现；不是当前每日扫描入口。

## 已完成验证

| 检查 | 结果与范围 |
| --- | --- |
| Python 语法 | 179 个受版本控制的 Python 文件；146 个非 archive 文件全部通过；archive 内 1 个既有语法错误，见下文 |
| Shell / SLURM 语法 | 74 个 `.sh` / `.sbatch` 全部通过 `bash -n`，未提交作业 |
| 在用测试脚本 | 30/30 通过；214 个 unittest 用例加 25 个自定义用例，共 239 个 |
| 主要命令行入口 | `scripts/` 下 41 个含 `ArgumentParser` 的非测试脚本，`--help` 全部退出 0；此项只验证启动、导入和参数解析 |
| 工作流版本 | 正文解析为 v4.144，与 changelog 首行一致，无同步告警 |
| 公司分析索引 | 使用真实本地输入成功生成 5,551 行，输出隔离在 `/tmp/raykey_structure_audit/` |
| 决策日志归档 | 归档前 44,893 行均逐行完整保留在现行文件与归档文件的并集中；另外新增 2 行 |
| 扫描台账归档 | 归档前 16,143 行的全部非空字段值均保留；其中 168 行补齐原本为空的两个互不重叠 5 年块字段；拆分后现行 140 行 m2、归档 29,643 行 m1 |
| 按臂索引生成 | 只读重建成功，得到 1,308 行索引，累计覆盖 29,783 行现行与归档记录；这不等同于独立试验数量验证 |
| Markdown 本地链接 | 扫描 712 个 Markdown 文件，发现 32 个缺失目标：10 个为本次核心池迁移问题，22 个位于旧诊断报告且精简前已缺失 |

## 既有问题与验证边界

- `scripts/archive/justified_multiple.py:152` 在本机 Python 3.11 下报 `f-string expression part cannot include a backslash`。已对照精简前提交确认原样存在，不归因于本次修改。
- `docs/archive/Ashare_workflow_diagnostic_report_20260714.md` 的 22 个失效链接在精简前的受版本控制目录树中已缺失，不归因于本次修改。
- 公司分析索引可成功重建，但当前入库文件有 214 行与重建结果不同；它是按需物化视图，不能把“脚本可运行”解释为“现有视图已刷新”。本次未覆写该文件。
- 未执行联网取数、全市场扫描、完整估值重建或长时回测；未验证市场数据覆盖、远端服务可用性、SLURM 实际资源分配或策略收益正确性。需要外部数据或长时计算的环节不在本次通过范围内。
- 本地回归使用桩数据或临时输出，未执行清理器的 `--apply`，未改写生产表或历史实验结果。

## 复核入口

以下检查均可本地执行；完整生产链应在上述迁移问题修复后按工作流运行。

```bash
python3 scripts/test_strategy_parameter_sync.py
python3 scripts/test_failure_semantics.py
python3 scripts/test_core_valuation_pool_l4.py
python3 scripts/archive/test_full_market_screen_queue.py
python3 scripts/build_a_share_company_analysis_index.py \
  --output-csv /tmp/raykey_company_index.csv \
  --output-md /tmp/raykey_company_index.md
```

第四条是上述已确认失败的复现入口；现有 L4 测试通过并不覆盖 Markdown 链接目标是否存在。审核时的逐脚本测试日志、CLI 日志及路径明细保存在 `/tmp/raykey_structure_audit/`，属于临时检查产物。
