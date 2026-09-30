# OI-245 第三段：水平守卫加当期 EPS 下限

预登记见 `preregister.md`（提交 cb6d4c1c），读数见 `readings3.md`，日志 §12.300。

- `observations3.py`：在第二段口径上加带键、`eps_ttm`、`bps_operating`，算 LG1.3（复现）、LG1.3F／LG1.6F／LG2.0F 与 OI-246 的 R1、PR、BR。输出 `observations3.csv`，也供 `../exp_oi246_20260930/` 使用。
- `analyze3.py`：复用第二段的回归与公允性函数；按第二段调用次序复现 LG1.3，再出各候选、被撤回部分与 R1 的 λ，以及现行池个案 `cases3.csv`。

    sbatch scripts/slurm/oi245c.sbatch
