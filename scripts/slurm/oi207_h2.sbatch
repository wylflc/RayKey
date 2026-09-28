#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi207_h2
#SBATCH --output=logs/oi207_h2_%j.out
#SBATCH --error=logs/oi207_h2_%j.err
# OI-207 H2 落地检验：生产逐日状态银行行按 H2 改写 → BASE／H2 14 起点全／A／U → 读数标记、第 13 款、第 11 款、当前银行
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi207_h2_20260928
/usr/bin/time -v python3 make_states.py
/usr/bin/time -v python3 run.py
