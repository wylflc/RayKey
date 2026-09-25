#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi215_inputs
#SBATCH --output=logs/oi215_inputs_%j.out
#SBATCH --error=logs/oi215_inputs_%j.err
# OI-215：现行解析规则并入人工核定表，缓存原文重解析附注现金类与受限资产两表到实验目录（生产表不动）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi215_20260925
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 inputs.py
