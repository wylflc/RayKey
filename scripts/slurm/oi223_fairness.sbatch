#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi223_fair
#SBATCH --output=logs/oi223_fair_%j.out
#SBATCH --error=logs/oi223_fair_%j.err
# OI-223 公允性检验：CONTROL 对 TIERS → 月末 P/V 与 3／5 年前向总回报（含按档、按杠杆组校准与 2015 年起子样本）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi223_20260928/control_validation.json
cd data/experiments/exp_oi223_20260928
FAIR_ARM=TIERS /usr/bin/time -v python3 fairness.py
