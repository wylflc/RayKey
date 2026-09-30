#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=48
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi241_run
#SBATCH --output=logs/oi241_run_%j.out
#SBATCH --error=logs/oi241_run_%j.err
# OI-241（v4.221 状态）：已持仓加仓改按建仓条件 A5／A2 与分解对照 X2，参照 S15（现行 BASE）；全样本、A、逐新臂 U、UC（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi241_20260930
WORKERS=46 /usr/bin/time -v python3 run.py
