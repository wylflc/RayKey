#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:35:00
#SBATCH --job-name=oi186_cooldown
#SBATCH --output=logs/oi186_cooldown_%j.out
#SBATCH --error=logs/oi186_cooldown_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 data/experiments/exp_oi186_20260914/run.py
