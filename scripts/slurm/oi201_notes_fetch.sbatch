#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=04:00:00
#SBATCH --job-name=oi201_notes
#SBATCH --output=logs/oi201_notes_%j.out
#SBATCH --error=logs/oi201_notes_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 scripts/fetch_cash_note_items.py --workers ${WORKERS:-24}
