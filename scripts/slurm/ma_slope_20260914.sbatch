#!/bin/bash
#SBATCH -J rk_ma_slope
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
E=data/experiments/exp_ma_slope_20260914
python3 "$E/run.py" --workers 48 --resume
python3 "$E/analyze.py"
python3 "$E/signals.py" --stage current
python3 "$E/register.py"
