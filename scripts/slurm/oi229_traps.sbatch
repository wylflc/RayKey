#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:30:00
#SBATCH --job-name=oi229_traps
#SBATCH --output=logs/oi229_traps_%j.out
#SBATCH --error=logs/oi229_traps_%j.err
# OI-229：答案卷 v1 在册股票月的 10 个新时点特征与 E1 → 陷阱识别读数 T1～T7（preregister.md）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi229_20260929
/usr/bin/time -v python3 traps229.py features
/usr/bin/time -v python3 traps229.py readings
