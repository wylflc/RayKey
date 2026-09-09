#!/bin/bash
#SBATCH -J rk_fracprepare
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python3 data/experiments/exp_buy_fraction_operating_20260909/prepare.py
