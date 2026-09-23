#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=03:00:00
#SBATCH --job-name=oi200_rescan
#SBATCH --output=logs/oi200_rescan_%j.out
#SBATCH --error=logs/oi200_rescan_%j.err
# §12.1：新口径（NEW 状态、对齐买入线）上换仓边际 0.10～0.20 按 0.01 重扫，全样本 + 去赢家 A、14 起点
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi200_203_20260923
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 rescan.py
