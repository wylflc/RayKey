#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=04:00:00
#SBATCH --job-name=oi219_fetch
#SBATCH --output=logs/oi219_fetch_%j.out
#SBATCH --error=logs/oi219_fetch_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 scripts/fetch_restricted_cash_items.py --workers ${WORKERS:-16}
