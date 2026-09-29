#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:30:00
#SBATCH --job-name=oi235_smoke
#SBATCH --output=logs/oi235_smoke_%j.out
#SBATCH --error=logs/oi235_smoke_%j.err
# OI-235（v4.221 状态）：BTNS 参照、NS 对照、BASE 现行；A 加仓同建仓条件＋小档、B 盈利偏离让位做 T、C 买入线以上卖出（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi235_20260929
SMOKE=1 /usr/bin/time -v python3 run.py
