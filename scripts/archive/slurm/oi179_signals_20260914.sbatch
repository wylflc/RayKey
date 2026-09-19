#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:20:00
#SBATCH --job-name=oi179_signals
#SBATCH --output=logs/oi179_signals_%j.out
#SBATCH --error=logs/oi179_signals_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 data/experiments/exp_oi179_20260914/post/signals.py
python3 data/experiments/exp_oi179_20260914/post/validate_extra.py
python3 scripts/experimental/pv_episode_forward.py --states data/experiments/exp_oi167_land_20260913/states/states_base.csv --out data/experiments/exp_oi179_20260914/pv --horizon 250
