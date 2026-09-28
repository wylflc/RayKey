#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi224_b2
#SBATCH --output=logs/oi224_b2_%j.out
#SBATCH --error=logs/oi224_b2_%j.err
# OI-224 第二批（v4.215 状态）：BASE、DPs／RE 重跑与 LS／DPt／SZ（含 E1 变体）14 起点全样本与剔除集 A → 读数
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_land_v4215_20260928/states/H2/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi224_exec2_20260928
/usr/bin/time -v python3 run.py
/usr/bin/time -v python3 readings.py
