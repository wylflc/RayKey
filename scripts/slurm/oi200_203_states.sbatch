#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:30:00
#SBATCH --job-name=oi200_states
#SBATCH --output=logs/oi200_states_%j.out
#SBATCH --error=logs/oi200_states_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_oi200_203_20260923
if [ ! -f "$E/before_manifest.json" ]; then /usr/bin/time -v python3 $E/prepare.py; fi
cd $E
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 verify.py
/usr/bin/time -v python3 align_check.py
