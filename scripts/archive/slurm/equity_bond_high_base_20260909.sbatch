#!/bin/bash
#SBATCH -J rk_ebhighbase
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:40:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python3 data/experiments/exp_equity_bond_20260909/prepare_high_base.py
python3 data/experiments/exp_equity_bond_20260909/run_high_base.py --workers 48
