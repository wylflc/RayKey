#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi200_verify
#SBATCH --output=logs/oi200_verify_%j.out
#SBATCH --error=logs/oi200_verify_%j.err
# 状态作业超时时补跑：校验三臂并切面板子集，再做买入线对齐检查
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi200_203_20260923
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py
