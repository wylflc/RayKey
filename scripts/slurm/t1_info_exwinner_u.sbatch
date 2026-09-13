#!/bin/bash
#SBATCH -J rk_t1u
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.1 第 4 款：在剔除集 A 下全面优秀的 SC 与 T1_GAIN 走剔除集 U（A ∪ 挑战臂前五）复核。用法：
#   sbatch scripts/slurm/t1_info_exwinner_u.sbatch
# 前置：exp_t1_info/sweep_t1.txt 第一遍已跑（各臂锚定起点 summary 在 data/backtest/）。配置只含 BASE＋两挑战臂（configs/t1_u.txt）。
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXP=data/experiments/exp_t1_info
for ARM in SC T1_GAIN; do
  echo "=== [$(date +%T)] 剔除集对称性：挑战臂 $ARM ==="
  python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/t1_u.txt" --challenger "$ARM" \
    --out "$EXP/exwinner_u_${ARM}.txt" --workers 56 | tee "$EXP/exwinner_u_${ARM}_report.txt"
done
echo "=== [$(date +%T)] 完成 ==="
