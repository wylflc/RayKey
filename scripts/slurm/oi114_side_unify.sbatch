#!/bin/bash
#SBATCH -J rk_oi114u
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-114 两侧口径统一：候选侧也改读持仓侧的 max(BASE,B2) 状态。
#   MAXBOTH 两侧同读 max 文件，两线按 align_buy_line.py 重解到同一下侧合格面（0.9190/0.1413）；
#   MAXRAW  同样换文件但**不重解线**，量「只换文件」会错多少（§12.1 禁止据此下结论，只作诊断）；
#   UNIBASE 反向统一：持仓侧退回候选侧的 BASE 状态（= v4.92 SPA 落地前口径），线本就解在该文件上。
# 4 臂 × 23 起点 × 两遍 = 184 次运行；--workers 48 实测峰值 55 GB，低于 -n 64 的 112 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/processed/experiments/exp_oi114_side_unify

echo "=== [$(date +%H:%M:%S)] 4 臂 × 23 起点 × 两遍 = 184 次运行 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/unify_arms.txt" \
  --out "$EXP/sweep_unify.txt" \
  --workers 48 \
  --title "两侧口径统一：候选侧改读 max(BASE,B2)（OI-114）" \
  | tee "$EXP/sweep_unify_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
