#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi245
#SBATCH --output=logs/oi245_%j.out
#SBATCH --error=logs/oi245_%j.err
# OI-245：全池股票月份检验非金融增长路径三处偏乐观来源（预登记 exp_oi245_20260930/preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi245_20260930
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4
/usr/bin/time -v python3 observations.py
/usr/bin/time -v python3 analyze.py
