#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi204_bt
#SBATCH --output=logs/oi204_bt_%j.out
#SBATCH --error=logs/oi204_bt_%j.err
# OI-204／211：14 起点全／A／U 回测 → 配对读数 → 信号层三表与归因 → 当前池
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi204_211_20260924
/usr/bin/time -v python3 run.py
python3 analyze.py
python3 diagnostics.py
python3 current.py
