#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=128
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:30:00
#SBATCH --job-name=oi247_run
#SBATCH --output=logs/oi247_run_%j.out
#SBATCH --error=logs/oi247_run_%j.err
# OI-247：止损两方案 18 臂 × 14 起点（全样本、A、逐新臂 U），参照 S15（预登记 exp_oi247_20260930/preregister.md，提交 cb6d4c1c）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi247_20260930
WORKERS=124 /usr/bin/time -v python3 run.py
