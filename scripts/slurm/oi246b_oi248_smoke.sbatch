#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi246b_248_smoke
#SBATCH --output=logs/oi246b_oi248_smoke_%j.out
#SBATCH --error=logs/oi246b_oi248_smoke_%j.err
# OI-246 第二段（A2 回测臂）与 OI-248（加仓后回落）冒烟：2011-11-01 起点，S15 复现与开关生效（预登记 95a068df）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
(cd data/experiments/exp_oi246b_20261001 && WORKERS=3 python3 run.py --smoke) &
(cd data/experiments/exp_oi248_20261001 && WORKERS=4 python3 run.py --smoke) &
wait
