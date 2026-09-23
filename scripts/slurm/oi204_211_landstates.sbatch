#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi204_lstates
#SBATCH --output=logs/oi204_lstates_%j.out
#SBATCH --error=logs/oi204_lstates_%j.err
# OI-204／211 落地臂 EFL：EF 同参、按裁定重定义的 §6.5.3 输出列全市场重建 → 与 EF 只许输出列不同
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi204_211_20260924
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
# STAGE=verify 只重跑核验（重建已完成时用）
if [ "${STAGE:-all}" != verify ]; then EXP_ARMS=EFL /usr/bin/time -v python3 build.py; fi
/usr/bin/time -v python3 land_verify.py
