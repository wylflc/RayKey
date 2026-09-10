# 30%／3.5pp采纳前评估

规则与范围在 [preregister.md](preregister.md)；只评估已选中的C030R35，不从邻域重新挑选赢家。当前对照为E2 BASE，所有数值沿用m3和修复后的记账。结论见仓库 `docs/reports/c030r35_adoption_2026-09-10.md`。

## 复现

```bash
python3 data/experiments/exp_c030r35_adoption_20260910/test_adapter.py
python3 data/experiments/exp_c030r35_adoption_20260910/test_integrity.py
sbatch --account=tes21035 scripts/slurm/c030r35_adoption_20260910.sbatch
# 作业成功后执行
python3 data/experiments/exp_c030r35_adoption_20260910/analyze_eval.py
python3 data/experiments/exp_c030r35_adoption_20260910/signal_report.py
python3 data/experiments/exp_c030r35_adoption_20260910/plots.py
python3 data/experiments/exp_c030r35_adoption_20260910/register.py
```

`prepare_eval.py`校验上一轮全部输入哈希与价格末端，继承已验证的生产状态子集等价性，再冻结本轮源文件。运行期间不得修改manifest包含的文件。`run_eval.py`在同一SLURM分配内用48个回测进程与最多4个信号诊断进程；中心及BASE的全/A共56条路径须逐字段复现旧批。

`engine.py`复用上一轮冻结的状态机和交易引擎，只注入本批参数登记；BASE别名不改变原融资约束。`signals.py`执行原信号诊断，注入只读结果捕获以保留精确逐日配对值；原输出同时落盘。共同面板P/V表复用须校验两臂输入相同。

## 产物口径

- `summary_rows.csv`：各剔除集、参数、14起点的完整摘要；U=A与K5=A允许显式复用。
- `paired_metrics.csv`：全指标水平、同起点配对差中位、正号数。`ref`为实际比较对象。邻域／换仓正式判定对固定BASE；换仓另给同档BM对照；滑点CS对同档BS。
- `decisions.csv`、`decision_details.json`：§12.1初筛、U判定、回撤归并段与全部理由。
- `winner_doses.csv`、`margin_matched.csv`、`slippage.csv`：赢家K剂量、同换仓档比较、同滑点档压力。
- `sweep_full_A.txt`、`report_full_A.txt`：全52臂固定BASE标准全/A表；这里的滑点行用于描述，正式同成本判定读取`slippage.csv`。
- `annual_paths.csv`、`nonoverlap_blocks.csv`：逐起点完整／残年标记与真实日历年数年化的非重叠块。
- `anchors.csv`、`policy_actual_anchors.csv`、`policy_events.csv`：两长跑锚点、实际受限与切换日。
- `sig/`：标准信号原表、精确日数据、共享P/V分档及归因；`signal_comparison.csv`区分各臂全部有效日期的水平与共同日期的配对差，不用两个独立中位数相减。
- `manifest.json`、各`verification.json`、`registration.json`：输入、完整性和台账登记证据。

原始逐日NAV、交易流水与中间缓存保留在本地且不入Git；重新执行可恢复。首次作业26528653在输入核查阶段停止（诊断参数名修正，未产生候选结果）；正式作业26528686重新冻结全部输入。新增52个台账臂名中4个是先前方案复核，48个为新参数组合，其中35个候选、13个成本／换仓对照。历史同族先前72个登记臂名与本批不能视为独立统计样本。
