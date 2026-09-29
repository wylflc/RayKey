#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=96
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi236_run
#SBATCH --output=logs/oi236_run_%j.out
#SBATCH --error=logs/oi236_run_%j.err
# OI-236（v4.221 状态）：BTNS 参照；G 让位细扫、X 小档组合、VD V 回落退出、D 换仓逻辑合理化（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi236_20260929
WORKERS=90 /usr/bin/time -v python3 run.py
