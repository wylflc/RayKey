#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi233_run
#SBATCH --output=logs/oi233_run_%j.out
#SBATCH --error=logs/oi233_run_%j.err
# OI-233（v4.221 状态）：BASE 与 ZH／NS／BT／BTNS 共 8 臂 14 起点全样本与剔除集 A → 读数（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi233_20260929
/usr/bin/time -v python3 run.py
/usr/bin/time -v python3 readings.py
