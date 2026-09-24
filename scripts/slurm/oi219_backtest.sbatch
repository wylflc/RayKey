#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi219_bt
#SBATCH --output=logs/oi219_bt_%j.out
#SBATCH --error=logs/oi219_bt_%j.err
# OI-219：14 起点全／A／U 回测 → 配对读数 → 信号层三表与归因 → 当前池
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi219_20260925
/usr/bin/time -v python3 run.py
python3 analyze.py
python3 diagnostics.py
python3 current.py
