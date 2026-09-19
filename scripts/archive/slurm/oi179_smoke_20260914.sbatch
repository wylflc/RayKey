#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:25:00
#SBATCH --job-name=oi179_smoke
#SBATCH --output=logs/oi179_smoke_%j.out
#SBATCH --error=logs/oi179_smoke_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 data/experiments/exp_oi179_20260914/prepare.py
python3 data/experiments/exp_oi179_20260914/audit.py
python3 data/experiments/exp_oi179_20260914/run.py --smoke --workers 1
python3 -m unittest discover -s scripts -p 'test_*.py' > logs/oi179_tests_${SLURM_JOB_ID}.out 2>&1
