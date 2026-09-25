#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi217f_fair
#SBATCH --output=logs/oi217f_fair_%j.out
#SBATCH --error=logs/oi217f_fair_%j.err
# OI-217 公允性检验：三臂全市场候选侧状态 → 月末 P/V 与 3／5 年前向总回报 → 预登记读数 1～6
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi217f_20260925
test -f build_validation.json
/usr/bin/time -v python3 fairness.py
