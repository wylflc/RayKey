# OI-247 现行策略的止损：未走强前的前低止损与长期水下减仓

预登记见 `preregister.md`（提交 cb6d4c1c），读数见 `readings.md`，日志 §12.302。

- `patch.py`：在内存中给原生回测引擎打补丁（不改 `scripts/backtest_valuation_strategy.py`），开关全关时逐位相同。
  - 方案一：前低止损锚的窗口与口径（`--bt-stop-window`、`--bt-stop-col`）、走强解除（`--bt-stop-release`）、锚缺失不设止损（`--bt-no-anchor-nostop`）。
  - 方案二：长期水下减仓（`--loss-age-days`、`--loss-age-keep`）。
- `engine.py`：打补丁后运行；全样本路径另留闭合周期（`trades/`）与逐日持仓（`snaps/`），锚点起点另留 `contrib_*_trades.csv`。
- `run.py`：18 臂 × 14 起点，全样本、A（S15 锚点前五）、逐新臂 U；S15 全样本对 `exp_land_v4225_20260930` 在册 NEW 行逐字段复现（`reproduction.json`）。输出 `sweep_full.txt`、`sweep_A.txt`、`u/`、`summary_rows.csv`、`run_manifest.json`。`--smoke` 为冒烟（`smoke.json`）。
- `readings.py`：预登记读数第 1～8 条，另出 OI-246 读数第 4 条（第七节）。输出 `readings.md`、`readings.json`。
- 作业：`scripts/slurm/oi247_run.sbatch`（27412990）、`scripts/slurm/oi247_readings.sbatch`（27413020）。

    python3 run.py
    python3 readings.py
