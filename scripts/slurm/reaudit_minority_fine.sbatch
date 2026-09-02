#!/bin/bash
#SBATCH -J rk_refine
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 F（买入线加密）与表 G（相关性上限加密）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
python3 scripts/sweep_backtest_configs.py "$EXP/configs/buyline_fine.txt" \
  --out "$EXP/sweep_buyline.txt" --workers 44 \
  --title "§12.171 表 F 买入线加密剂量（在册 1.0454）" | tee "$EXP/report_buyline.txt"
python3 scripts/sweep_backtest_configs.py "$EXP/configs/corr_fine.txt" \
  --out "$EXP/sweep_corr.txt" --workers 44 \
  --title "§12.171 表 G 相关性上限加密剂量（在册 0.70）" | tee "$EXP/report_corr.txt"
