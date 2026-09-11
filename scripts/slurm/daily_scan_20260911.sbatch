#!/bin/bash
#SBATCH -J rk_scan_0911
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH --mem-per-cpu=1792M
#SBATCH -t 00:15:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/fetch_equity_bond_inputs.py --refresh
python3 scripts/fetch_cost_of_equity_inputs.py
bash scripts/slurm/daily_postclose.sbatch
