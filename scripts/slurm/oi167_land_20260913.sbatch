#!/bin/bash
#SBATCH -J rk_oi167land
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:55:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
# RAYKEY_ROOT 允许在仓库副本（如项目空间配额受限时的 scratch 克隆）上运行；缺省为正式仓库
cd "${RAYKEY_ROOT:-/gpfs/work1/0/qt15419/zwang/mm_quant/RayKey}"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
python3 -m unittest discover -s scripts -p 'test_*.py' > data/experiments/exp_oi167_land_20260913/tests.txt 2>&1
python3 data/experiments/exp_oi167_land_20260913/run.py --workers 14
