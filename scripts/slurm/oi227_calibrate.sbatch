#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi227_cal
#SBATCH --output=logs/oi227_cal_%j.out
#SBATCH --error=logs/oi227_cal_%j.err
# OI-227 第一步：同尺校准银行偏差 c 与折算的银行买入线（v4.215 H2 状态）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi227_20260928
/usr/bin/time -v python3 calibrate.py
