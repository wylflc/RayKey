#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi227_recal
#SBATCH --output=logs/oi227_recal_%j.out
#SBATCH --error=logs/oi227_recal_%j.err
# OI-227 落地前重估：v4.216 非金融口径下的银行偏差 c 与缩放系数 k
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi227_20260928
/usr/bin/time -v python3 recalibrate_v4216.py
