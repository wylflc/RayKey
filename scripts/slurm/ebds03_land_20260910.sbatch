#!/bin/bash
#SBATCH -J rk_ebds03land
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:40:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# v4.176 落地核对：新 BASE 正式扫描 28 路径须与 §12.223 EBDS03 逐值相同，归并台账、重登在册（§12.226）。
# 用法：sbatch --account=tes21035 scripts/slurm/ebds03_land_20260910.sbatch
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 data/experiments/exp_ebds03_land_20260910/run.py --workers 56
