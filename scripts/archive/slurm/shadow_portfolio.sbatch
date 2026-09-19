#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:05:00
#SBATCH --job-name=shadow_e4
#SBATCH --output=logs/shadow_e4_%j.out
#SBATCH --error=logs/shadow_e4_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 -u scripts/shadow_portfolio.py run
