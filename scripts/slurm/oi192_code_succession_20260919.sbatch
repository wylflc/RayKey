#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi192
#SBATCH --output=logs/oi192_%j.out
#SBATCH --error=logs/oi192_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_code_succession_20260919
if [ ! -f "$E/states_validation.json" ]; then python3 "$E/run_states.py"; fi
python3 "$E/run.py"
python3 "$E/post/analyze.py"
