#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi220_wc
#SBATCH --output=logs/oi220_wc_%j.out
#SBATCH --error=logs/oi220_wc_%j.err
# OI-220 量级：质押开票存单计入营运资金，池内 79 只子集两臂建带对照
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_aima_growth_20260925
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 pledged_wc.py
