#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi245b
#SBATCH --output=logs/oi245b_%j.out
#SBATCH --error=logs/oi245b_%j.err
# OI-245 第二段：利润基数高位的成因与水平守卫候选（预登记 exp_oi245b_20260930/preregister.md，提交 deef26c9）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi245b_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
/usr/bin/time -v python3 observations2.py
/usr/bin/time -v python3 analyze2.py
