#!/bin/bash
#SBATCH -J rk_c030land
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:20:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python3 -m unittest discover -s scripts -p 'test_*.py' > data/experiments/exp_c030r35_land_20260910/tests.txt 2>&1
python3 data/experiments/exp_c030r35_land_20260910/run.py --workers 12
