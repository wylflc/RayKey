#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi245c
#SBATCH --output=logs/oi245c_%j.out
#SBATCH --error=logs/oi245c_%j.err
# OI-245 第三段：水平守卫加当期 EPS 下限（预登记 exp_oi245c_20260930/preregister.md，提交 cb6d4c1c）；另出 OI-246 共用观测与 R1 λ
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi245c_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
/usr/bin/time -v python3 observations3.py
/usr/bin/time -v python3 analyze3.py
