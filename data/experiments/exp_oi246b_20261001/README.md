# OI-246 第二段：谷底守卫深跌不买（A2）回测臂

预登记见 `preregister.md`（提交 95a068df），读数见 `readings.md`，日志 §12.303。

- `prep.py`：由现行候选侧状态（`a_share_daily_states_adopted.csv`）所挂带与 `roic_bands.csv` 的 `trough_weight` 生成逐票 v 分段 `trough_v.csv`（不入库，重跑即得）。
- `patch.py`：在内存中给原生回测引擎打补丁（不改 `scripts/backtest_valuation_strategy.py`），开关全关时逐位相同。`--ta-drop`、`--ta-vmin`、`--ta-v-file`：信号日 250 日回报 < −D 且 v 达门槛的新建仓挡下。
- `engine.py`：打补丁后运行；全样本路径另留闭合周期（`trades/`）与挡下记录（`blocks/`）。
- `run.py`：6 臂 × 14 起点，全样本、A（S15 锚点前五）、逐新臂 U；S15 全样本对 `exp_land_v4225_20260930` 在册 NEW 行逐字段复现（`reproduction.json`）。`--smoke` 为冒烟（`smoke.json`）。
- `readings.py`：预登记读数第 1～8 条。输出 `readings.md`、`readings.json`。
- 作业：`scripts/slurm/oi246b_oi248_smoke.sbatch`（27416891）、`oi246b_run.sbatch`（27417121）、`oi246b_readings.sbatch`（27417125）。

    python3 run.py
    python3 readings.py
