#!/bin/bash
#SBATCH -J rk_swaprepeat
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:20:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
E=data/experiments/exp_swap_repeat_candidate_20260917
if [ "${STAGE:-scan}" = smoke ]; then
    python3 "$E/run.py" prepare
    /usr/bin/time -v python3 "$E/run.py" smoke
else
    python3 "$E/run.py" scan --workers 24
fi
