#!/bin/bash
#SBATCH --job-name=oi197-audit
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --output=logs/oi197_audit_%j.out
#SBATCH --error=logs/oi197_audit_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 data/experiments/exp_oi197_20260921/audit.py
