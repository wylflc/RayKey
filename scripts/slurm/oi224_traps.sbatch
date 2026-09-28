#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=oi224_traps
#SBATCH --output=logs/oi224_traps_%j.out
#SBATCH --error=logs/oi224_traps_%j.err
# OI-224 第一步：答案卷 v1 在册股票月的 15 个时点特征 → 陷阱识别读数 T1～T5
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi224_traps_20260928
/usr/bin/time -v python3 traps.py features
/usr/bin/time -v python3 traps.py readings
