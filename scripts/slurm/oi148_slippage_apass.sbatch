#!/bin/bash
#SBATCH -J rk_oi148a
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-148 补跑剔除集 A（按 0bp 锚点固定：BASE 2011-11-01 前五赢家）单遍，并重出报告。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi148_slippage
python3 scripts/sweep_backtest_configs.py "$EXP/configs/slip_tiers.txt" --out "$EXP/sweep_tiers_A.txt" --workers 58 \
  --exclude-codes 000338,000651,000933,002128,601088 \
  --title "OI-148 剔除集 A（BASE 0bp 锚点前五赢家固定）" | tee "$EXP/report_tiers_A.txt"
python3 scripts/experimental/oi148_slippage_report.py --exp "$EXP" | tee "$EXP/report.txt"
echo "=== [$(date +%T)] 完成 ==="
