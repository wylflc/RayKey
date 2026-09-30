#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi247_readings
#SBATCH --output=logs/oi247_readings_%j.out
#SBATCH --error=logs/oi247_readings_%j.err
# OI-247 读数（preregister.md 第 1～8 条），另出 OI-246 读数第 4 条；须在 oi247_run 完成后跑
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi247_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
test -f summary_rows.csv
/usr/bin/time -v python3 readings.py
