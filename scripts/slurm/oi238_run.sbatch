#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=96
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi238_run
#SBATCH --output=logs/oi238_run_%j.out
#SBATCH --error=logs/oi238_run_%j.err
# OI-238（v4.221 状态）：让位减仓加「未创新高」条件，参照 BASE 与未过滤臂；全样本、A、逐新臂 U、UC（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi238_20260930
WORKERS=90 /usr/bin/time -v python3 run.py
