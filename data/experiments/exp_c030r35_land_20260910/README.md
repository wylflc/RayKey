# C030R35生产基准落地与重登

用户在§12.228评估后明确采纳。规则见[工作流程§9.3.1](../../../docs/000_Ashare_workflow.md)，结论及适用范围见[落地报告](../../../docs/reports/c030r35_landing_2026-09-10.md)、回测日志§12.229。

正式生产BASE的14起点全样本／去赢家A共28条路径，与采纳前研究候选比较；另跑旧E2参数两个长跑锚点。`engine.py`仅截取原引擎已算出的未舍入净值记录，没有替换信号或交易函数。共享信号另外与原候选历史状态作258个观测比较。

## 执行与重现

正式回测作业为26530989，16核申请、12个回测并发，全套393项脚本测试通过，30条交易路径全部完成。脚本入口：

```bash
sbatch --account=tes21035 scripts/slurm/c030r35_land_20260910.sbatch
python3 data/experiments/exp_c030r35_land_20260910/register.py
```

运行前应按仓库要求清理过期日志并检查资源；原输入哈希不一致时禁止把新结果称为本批复现。`run.py`以c24ea622的正式BASE及上一批manifest为参照，仅允许本轮生产脚本变动。新批次应另建目录，保留这里的冻结证据。

原作业在全部回测完成后，因一个描述项的末位浮点字符串差异退出；`first_run_diagnostic.json`保存独立清查结果。随后仅调整该描述项比较精度，以单进程核验既有产物，未重跑交易：

```bash
python3 data/experiments/exp_c030r35_land_20260910/run.py --verify-existing --workers 1
```

原manifest保留。`verification.json`记录比较器及精度说明的前后哈希；最终文档整理相对运行时的差异在`completion_checks.json`另记，不属于交易输入修改。日后重验本批，应使用manifest记录的运行时输入版本与记录过的比较器修订，不能混用新数据。

`register.py`须先通过核验门槛，校对每个私有摘要与已验证摘要行，再原子刷新28份标准`data/backtest/summary_BASE*.csv`，仅经`clean_derived_artifacts.write_ledger`入账；支持幂等重入。首次写入后的比较器遗漏并集列头空列，后补空列规范化重入通过，回测数字未改。`registration.json`中的`newly_added_keys=0`指重入当次，相对冻结台账实际新增28行由`added_keys_vs_frozen_ledger=28`记录。冻结旧台账3,066行逐值保留；总计3,094行。

## 证据文件

| 文件 | 内容 |
| --- | --- |
| `preregister.md`、`manifest.json` | 事前核验范围、输入哈希、正式BASE参数、等价面板证据和价格末端 |
| `summary_rows.csv`、`path_checks.csv` | 28条新BASE与2条旧E2锚点摘要、完整起点和窗口校验 |
| `sweep_base.txt`、`report_sweep_base.txt` | 新BASE的28路径标准扫描格式与在册报表；BASE对自身差为0，不是重新检验候选资格 |
| `in_register.json` | 全/A在册字段水平中位和长跑锚点；日期字段的数值中位只保留程序原始输出，不作日历日期解释，日期应读逐路径摘要 |
| `signal_equivalence.csv`、`current_signal.json` | 历史观测逐点核对及2026-09-10本地最新信号状态 |
| `verification.json`、`first_run_diagnostic.json` | 完整核验与唯一描述项约1.11e-16差异、精度修订证据 |
| `registration.json` | 标准摘要发布哈希、旧台账保留、新增28键、赢家读取与台账回退核验 |
| `tests.txt`、`resources.json`、`completion_checks.json` | 测试、作业资源及最终文档／账户连续性检查 |

`cache/`、`nav/`、`daily/`、`errors/`为可重建大产物，不纳入Git。逐日净值文件共100,114行，约束流水100,084行，与原候选／旧E2对应文件字节一致；2,460摘要字段中仅一项描述性比例有最后一位差异，全部决策、标准指标与滚五序列完全相同。

本次只落实已选方案，成本／平台／收益稳定性的未过项保留，未生成样本外证据，也没有把其余候选相对旧E2的资格转移到新BASE。
