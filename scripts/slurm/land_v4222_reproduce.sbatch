#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=96
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:50:00
#SBATCH --job-name=land_reproduce
#SBATCH --output=logs/land_reproduce_%j.out
#SBATCH --error=logs/land_reproduce_%j.err
# v4.222 落地核对：原生引擎（bt_quiet／swap_ext 已移入）逐字段复现 OI-237 的 BASE 与 S15 行（14 起点 × 全样本／A／UC）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_land_v4222_20260930
WORKERS=90 /usr/bin/time -v python3 reproduce.py
