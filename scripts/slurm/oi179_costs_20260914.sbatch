#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:25:00
#SBATCH --job-name=oi179_costs
#SBATCH --output=logs/oi179_costs_%j.out
#SBATCH --error=logs/oi179_costs_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
if [[ ${OI179_COST_REUSE:-0} == 1 ]]; then
    python3 data/experiments/exp_oi179_20260914/post/costs.py --reuse-completed
else
    python3 data/experiments/exp_oi179_20260914/post/costs.py
fi
