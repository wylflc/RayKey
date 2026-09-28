#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi207_banks
#SBATCH --output=logs/oi207_banks_%j.out
#SBATCH --error=logs/oi207_banks_%j.err
# OI-207 银行估值多方法检验：STAGES（空格分隔，缺省全部）= prepare methods analyze
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi207_20260928
for s in ${STAGES:-prepare methods analyze}; do /usr/bin/time -v python3 bank_methods.py $s; done
