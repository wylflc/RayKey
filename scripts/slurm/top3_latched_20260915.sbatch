#!/bin/bash
#SBATCH --job-name=rk_top3_latched
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:10:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 -u scripts/experimental/top3_period_forward.py --eligibility stop-latched --out data/experiments/exp_top3_latched_20260915
