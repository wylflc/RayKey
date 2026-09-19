#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=ma60c4
#SBATCH --output=logs/ma60_clause4_%j.out
#SBATCH --error=logs/ma60_clause4_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_ma60_clause4_20260919
python3 "$E/run.py" --workers 48
python3 "$E/post/analyze.py"
