#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:20:00
#SBATCH --job-name=oi196_audit
#SBATCH --output=logs/oi196_audit_%j.out
#SBATCH --error=logs/oi196_audit_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
/usr/bin/time -v python3 scripts/experimental/audit_same_day_distributions.py \
    --out data/experiments/exp_oi196_20260921 --workers 4
