#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:30:00
#SBATCH --job-name=oi224_b1
#SBATCH --output=logs/oi224_b1_%j.out
#SBATCH --error=logs/oi224_b1_%j.err
# OI-224 第一批：E1 时点表 → BASE 与 DPs／RE（含 E1 变体）14 起点全样本与剔除集 A → 读数
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_land_v4213_20260928/states/RO/a_share_daily_states_adopted.csv
cd data/experiments/exp_oi224_exec_20260928
python3 e1_table.py
/usr/bin/time -v python3 run.py
/usr/bin/time -v python3 readings.py
