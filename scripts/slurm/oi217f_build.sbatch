#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi217f_build
#SBATCH --output=logs/oi217f_build_%j.out
#SBATCH --error=logs/oi217f_build_%j.err
# OI-217 公允性检验：核对 exp_oi217u 冻结输入 → W（净负债加权）v4.208 候选侧重建 → 与 C／U 带逐行核对
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi217f_20260925
/usr/bin/time -v python3 build.py
