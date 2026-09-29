#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi236_smoke
#SBATCH --output=logs/oi236_smoke_%j.out
#SBATCH --error=logs/oi236_smoke_%j.err
# OI-236（v4.221 状态）：BTNS 参照；G 让位细扫、X 小档组合、VD V 回落退出、D 换仓逻辑合理化（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi236_20260929
SMOKE=1 /usr/bin/time -v python3 run.py
