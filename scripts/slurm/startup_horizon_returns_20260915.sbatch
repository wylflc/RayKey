#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:20:00
#SBATCH --job-name=startup_returns
#SBATCH --output=logs/startup_returns_%j.out
#SBATCH --error=logs/startup_returns_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 -u scripts/experimental/startup_horizon_returns.py run \
  --out data/experiments/exp_startup_returns_20260915 --workers 24
