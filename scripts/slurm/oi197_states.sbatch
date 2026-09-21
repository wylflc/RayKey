#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi197_states
#SBATCH --output=logs/oi197_states_%j.out
#SBATCH --error=logs/oi197_states_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
if [[ "${SKIP_PREPARE:-0}" != "1" ]]; then
    /usr/bin/time -v python3 data/experiments/exp_oi197_20260921/prepare.py
fi
/usr/bin/time -v python3 data/experiments/exp_oi197_20260921/build.py
