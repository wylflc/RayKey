#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi249_run
#SBATCH --output=logs/oi249_run_%j.out
#SBATCH --error=logs/oi249_run_%j.err
# OI-249：五臂重建带（对照、量驱动放宽、除商品型、roic0 同口径、合并）→ 月末观测 → 公允性读数（预登记 exp_oi249_20261001/preregister.md，提交 4bda89f1）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi249_20261001
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
/usr/bin/time -v python3 build.py
/usr/bin/time -v python3 observations4.py
/usr/bin/time -v python3 analyze4.py
