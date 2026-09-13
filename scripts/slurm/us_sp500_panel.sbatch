#!/bin/bash
#SBATCH -J us_sp500_panel
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/build_us_index_panel.py "$@"
