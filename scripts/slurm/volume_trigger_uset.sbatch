#!/bin/bash
#SBATCH -J rk_volu
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.1 第 4 款：成交量闸门第一阶段在剔除集 A 下全项不劣的 VT_E12 与 VS_MIN08 走剔除集 U（A ∪ 挑战臂前五）复核。用法：
#   sbatch scripts/slurm/volume_trigger_uset.sbatch
# 前置：第一阶段 sweep_stage1.txt 已跑且 summary 已归并进 data/backtest/scan_summaries.csv（赢家名单从台账同标签行读）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_volume_trigger
for ARM in VT_E12 VS_MIN08; do
  echo "=== [$(date +%T)] 剔除集对称性：挑战臂 $ARM ==="
  python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/vol_u.txt" --challenger "$ARM" \
    --out "$EXP/exwinner_u_${ARM}.txt" --workers 56 | tee "$EXP/exwinner_u_${ARM}_report.txt"
done
echo "=== [$(date +%T)] 完成 ==="
