# OI-249 候选 1、2：量驱动放宽峰守卫与 roic0 同口径

预登记见 `preregister.md`（提交 4bda89f1），读数见 `readings4.md`，日志 §12.305。

- `patch_builder.py`：在内存中给建带脚本打补丁（研究开关 `--peak-relax`、`--roic0-basis`，缺省关、逐位复现生产）。v4.226 起生产建带脚本自带与 C1／C1b 逐字相同的 `--peak-relax`，补丁对已有的块跳过，使本实验可重跑。
- `build.py`：五臂（ctrl、c1、c1b、c2、c12）并行重建样本代码与个案代码的带（`bands_<臂>.csv`，不入库），`build.json` 记返回码与开关计数。
- `observations4.py`：OI-245 第一段口径月末行 × 各臂带（精确 V'，带值未变的行沿用原 `P/V`），`observations4.csv`（不入库）与 `observations4_check.json`。
- `analyze4.py`：公允性 λ（复用 `../exp_oi245b_20260930/analyze2.py`）、分段、买入区占比、C1 命中构成与个案表，`readings4.json`、`readings4.md`。
- 作业：`scripts/slurm/oi249_run.sbatch`（27422058）；观测与读数在修正未变行的舍入噪声后交互重跑（λ 不变）。

    python3 build.py && python3 observations4.py && python3 analyze4.py
