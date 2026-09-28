#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi227_bt
#SBATCH --output=logs/oi227_bt_%j.out
#SBATCH --error=logs/oi227_bt_%j.err
# OI-227 第二步：BASE 与银行单独买入线三档 14 起点全样本与剔除集 A → 读数
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_land_v4215_20260928/states/H2/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi227_20260928
/usr/bin/time -v python3 run.py
/usr/bin/time -v python3 readings.py
