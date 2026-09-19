#!/bin/bash
#SBATCH -J rk_oidose
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:50:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/experimental/open_issue_dose_run.py --workers 56
