#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=land_v4224_rc
#SBATCH --output=logs/land_v4224_recheck_%j.out
#SBATCH --error=logs/land_v4224_recheck_%j.err
# v4.224：更正 P/V 比例方向后重跑 K1 对现行三侧逐行比对（build.py compare_k1），只改写 build_check.json 的 k1_vs_current
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_land_v4224_20260930
/usr/bin/time -v python3 recheck.py
