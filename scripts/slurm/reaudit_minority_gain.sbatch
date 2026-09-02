#!/bin/bash
#SBATCH -J rk_regain
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 E：涨幅减持阈值 × 走势闸门剂量扫描。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
python3 scripts/sweep_backtest_configs.py "$EXP/configs/gain_dose.txt" \
  --out "$EXP/sweep_gain.txt" --workers 44 \
  --title "§12.171 表 E 涨幅减持阈值 × 走势闸门在 OI-128 纪元上的剂量" \
  | tee "$EXP/report_gain.txt"
