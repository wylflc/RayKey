#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi205b_fair
#SBATCH --output=logs/oi205b_fair_%j.out
#SBATCH --error=logs/oi205b_fair_%j.err
# OI-205 v4.210 重测公允性检验：CONTROL／G 全市场候选侧状态 → 月末 P/V 与 3／5 年前向总回报 → 预登记读数 F1～F6
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi205b_20260928/control_validation.json
cd data/experiments/exp_oi205b_20260928
/usr/bin/time -v python3 fairness.py
