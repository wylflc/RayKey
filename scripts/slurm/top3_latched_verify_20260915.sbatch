#!/bin/bash
#SBATCH --job-name=rk_top3_latch_verify
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
python3 -u scripts/experimental/verify_top3_periods.py --source data/experiments/exp_top3_latched_20260915
python3 -u scripts/experimental/render_top3_periods.py --source data/experiments/exp_top3_latched_20260915 --report docs/reports/top3_latched_periods_2026-09-15.zh.md
