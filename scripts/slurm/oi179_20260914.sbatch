#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi179_fix
#SBATCH --output=logs/oi179_fix_%j.out
#SBATCH --error=logs/oi179_fix_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 data/experiments/exp_oi179_20260914/run.py --workers 48 --resume
python3 data/experiments/exp_oi179_20260914/analyze.py
