#!/bin/bash
#SBATCH -J rk_sb1chk
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -N 1
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/experimental/sb1_daily_buys_checks.py --workers 60
