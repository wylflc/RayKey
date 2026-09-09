#!/bin/bash
#SBATCH -J rk_m3rereg
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# m3 首批同批重算（§12.222／§12.223）：OI-169/170 记账修复后 BASE 在册重登（28 路径，正式扫描器）
# + EBDS02/EBDS03 全/A（84 路径，候选包装）+ 剔除集 U 单遍（U≠A 时 42 路径）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
python3 data/experiments/exp_m3_rereg_20260910/run.py --workers 56
