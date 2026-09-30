# OI-248 加仓后回落：只给盈利仓加仓与回落撤回加仓

预登记见 `preregister.md`（提交 95a068df），读数见 `readings.md`，日志 §12.304。

- `patch.py`：在内存中给原生回测引擎打补丁（不改 `scripts/backtest_valuation_strategy.py`），开关全关时逐位相同。
  - 规则一：`--add-gate M`，加仓另须信号日收盘 > 持仓均价 × (1 + M)。
  - 规则二：`--ab-drop D`（`--ab-ma`、`--ab-clear`、`--ab-keep`），加仓过且收盘 < 均价 × (1 − D) 时撤回到一档，撤回后锁定加仓至收盘回到均价以上。
- `engine.py`：打补丁后运行；全样本路径另留闭合周期（`trades/`）、逐日持仓（`snaps/`，含买入笔数与加仓锁）与规则记录（`events/`）。
- `run.py`：11 臂 × 14 起点，全样本、A（S15 锚点前五）、逐新臂 U；S15 全样本对 `exp_land_v4225_20260930` 在册 NEW 行逐字段复现（`reproduction.json`）。`--smoke` 为冒烟（`smoke.json`）。
- `readings.py`：预登记读数第 1～10 条。输出 `readings.md`、`readings.json`。
- 作业：`scripts/slurm/oi246b_oi248_smoke.sbatch`（27416891）、`oi248_run.sbatch`（27417124）、`oi248_readings.sbatch`（27417126）。

    python3 run.py
    python3 readings.py
