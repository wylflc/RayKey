#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:30:00
#SBATCH --job-name=oi233_smoke
#SBATCH --output=logs/oi233_smoke_%j.out
#SBATCH --error=logs/oi233_smoke_%j.err
# OI-233 冒烟（v4.221 状态）：锚点起点全样本 9 臂，补丁关闭时逐字段复现在册 BASE，各开关触发计数 → smoke.json
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi230_20260929/states/DC/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi233_20260929
SMOKE=1 /usr/bin/time -v python3 run.py
