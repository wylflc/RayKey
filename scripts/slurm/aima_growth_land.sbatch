#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=aima_growth
#SBATCH --output=logs/aima_growth_%j.out
#SBATCH --error=logs/aima_growth_%j.err
# v4.207 研究增长：爱玛登记 research_g0 → §6.7 第 4～6 步（信号日 2026-09-24）→ 重发当日执行清单 → 核对
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
E=data/experiments/exp_aima_growth_20260925
(cd $E && python3 register.py)
SIGNAL_DATE=2026-09-24 SINCE=2026-09-23 bash scripts/slurm/refresh_pool_from_bands.sbatch
(cd $E && python3 publish.py)
