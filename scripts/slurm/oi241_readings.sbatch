#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi241_readings
#SBATCH --output=logs/oi241_readings_%j.out
#SBATCH --error=logs/oi241_readings_%j.err
# OI-241 读数（preregister.md 第 1～8 条）：先重跑全样本落逐日持仓（snap.py），再出读数；须在 oi241_run 完成后跑
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi241_20260930
test -f summary_rows.csv
WORKERS=30 /usr/bin/time -v python3 snap.py
/usr/bin/time -v python3 readings.py
