#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=02:00:00
#SBATCH --job-name=oi206_fair
#SBATCH --output=logs/oi206_fair_%j.out
#SBATCH --error=logs/oi206_fair_%j.err
# OI-206 公允性检验：CONTROL 对 T12（主候选），再对 T08、T16 → 月末 P/V 与 3／5 年前向总回报
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
test -f data/experiments/exp_oi206_20260928/control_validation.json
cd data/experiments/exp_oi206_20260928
for arm in T12 T08 T16; do FAIR_ARM=$arm /usr/bin/time -v python3 fairness.py; done
