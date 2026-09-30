#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=128
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi248_run
#SBATCH --output=logs/oi248_run_%j.out
#SBATCH --error=logs/oi248_run_%j.err
# OI-248：加仓后回落 11 臂 × 14 起点（全样本、A、逐新臂 U），参照 S15（预登记 exp_oi248_20261001/preregister.md，提交 95a068df）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi248_20261001
WORKERS=124 /usr/bin/time -v python3 run.py
