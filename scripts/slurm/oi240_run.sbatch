#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=96
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi240_run
#SBATCH --output=logs/oi240_run_%j.out
#SBATCH --error=logs/oi240_run_%j.err
# OI-240（v4.221 状态）：CC 已持仓触发的仓位门槛 10～60%，参照 BASE、S15、CCS15；全样本、A、逐新臂 U、UC（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi240_20260930
WORKERS=90 /usr/bin/time -v python3 run.py
