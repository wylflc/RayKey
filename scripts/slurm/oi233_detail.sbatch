#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi233_detail
#SBATCH --output=logs/oi233_detail_%j.out
#SBATCH --error=logs/oi233_detail_%j.err
# OI-233 对比细读（v4.221 状态）：BASE／NS／BT3／BTNS × 14 起点，逐 (代码, 年) contrib 与月末持仓权重（只记账补丁）→ detail/（compare.py 读）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi233_20260929
WORKERS=14 /usr/bin/time -v python3 detail.py
