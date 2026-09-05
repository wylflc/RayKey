#!/bin/bash
#SBATCH -J rk_oi114f
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-114 换仓边际在 SPA（现行 BASE）上加密到 0.01 一档：0.15~0.24，定位全期年化最优点。
# 现行 0.1437 即 BASE 臂；0.10/0.25/0.35 与两端已在 §12.149 测过，本轮只补中段。
# 11 臂 × 23 起点 × 两遍 = 506 次运行；--workers 48 实测峰值 55 GB，低于 -n 64 的 112 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_oi114_margin_fine

echo "=== [$(date +%H:%M:%S)] 11 臂 × 23 起点 × 两遍 = 506 次运行 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/fine_arms.txt" \
  --out "$EXP/sweep_fine.txt" \
  --workers 48 \
  --title "换仓边际 0.15~0.24 加密（OI-114，按年化选点）" \
  | tee "$EXP/sweep_fine_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
