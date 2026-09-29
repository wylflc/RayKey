#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=96
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi237_run
#SBATCH --output=logs/oi237_run_%j.out
#SBATCH --error=logs/oi237_run_%j.err
# OI-237（v4.221 状态）：BTNS 与让位换仓的组合确认，参照 BASE；全样本、A、逐臂 U、共同剔除集 UC（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi237_20260930
WORKERS=90 /usr/bin/time -v python3 run.py
