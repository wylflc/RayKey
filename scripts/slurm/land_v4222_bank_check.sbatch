#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=64
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=land_bank_check
#SBATCH --output=logs/land_bank_check_%j.out
#SBATCH --error=logs/land_bank_check_%j.err
# v4.222 落地前核对：BASE 与 S15 在 OI-230 CONTROL（旧银行口径）状态上的 14 起点全样本与剔除集 A
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_land_v4222_20260930
WORKERS=58 /usr/bin/time -v python3 bank_check.py
