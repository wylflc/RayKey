#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi200_bt
#SBATCH --output=logs/oi200_bt_%j.out
#SBATCH --error=logs/oi200_bt_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi200_203_20260923
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 run.py
/usr/bin/time -v python3 analyze.py
/usr/bin/time -v python3 diagnostics.py
/usr/bin/time -v python3 current.py
