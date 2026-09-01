#!/bin/bash
#SBATCH -J rk_exwinsym
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 去赢家口径的对称性检验：现行剔除集取自 BASE 前五，对 BASE 自伤、对挑战臂顺风。
# 按 A(BASE 前五) / B(TW000 前五) / U(并集) 三组各跑 7 臂 × 14 起点 = 294 次运行。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/processed/experiments/exp_oi115_trailleg

python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/trail_arms.txt" \
  --challenger TW000 \
  --out "$EXP/exwin_symmetry.txt" \
  --workers 48

echo "=== [$(date +%H:%M:%S)] 完成 ==="
