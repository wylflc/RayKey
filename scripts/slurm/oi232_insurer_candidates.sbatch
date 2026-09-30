#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi232
#SBATCH --output=logs/oi232_%j.out
#SBATCH --error=logs/oi232_%j.err
# OI-232：保险估值六个候选的同尺偏差、利率反应与现值（预登记 exp_oi232_20260930/preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi232_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
/usr/bin/time -v python3 candidates.py
/usr/bin/time -v python3 analyze.py
