#!/bin/bash
#SBATCH --job-name=oi197-shadow
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:10:00
#SBATCH --output=logs/oi197_shadow_%j.out
#SBATCH --error=logs/oi197_shadow_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 data/experiments/exp_oi197_20260921/validate_shadow.py
