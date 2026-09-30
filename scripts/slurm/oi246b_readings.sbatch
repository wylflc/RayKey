#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi246b_readings
#SBATCH --output=logs/oi246b_readings_%j.out
#SBATCH --error=logs/oi246b_readings_%j.err
# oi246b 读数（preregister.md）；须在 oi246b_run 完成后跑
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi246b_20261001
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
test -f summary_rows.csv
/usr/bin/time -v python3 readings.py
