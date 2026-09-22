#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=pv_cap
#SBATCH --output=logs/pv_cap_%j.out
#SBATCH --error=logs/pv_cap_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PV_CAP_WORKERS=24
python3 data/experiments/exp_pv_cap_20260922/test_engine.py
if [[ ! -f data/experiments/exp_pv_cap_20260922/manifest.json ]]; then
  /usr/bin/time -v python3 data/experiments/exp_pv_cap_20260922/prepare.py
fi
/usr/bin/time -v python3 -u data/experiments/exp_pv_cap_20260922/run.py
