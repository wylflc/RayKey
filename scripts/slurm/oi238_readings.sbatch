#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi238_readings
#SBATCH --output=logs/oi238_readings_%j.out
#SBATCH --error=logs/oi238_readings_%j.err
# OI-238 读数（preregister.md 第 1～7 条）；须在 oi238_run 完成后跑
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi238_20260930
test -f summary_rows.csv
/usr/bin/time -v python3 readings.py
