#!/bin/bash
#SBATCH -J rk_m2reg
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -N 1
#SBATCH -n 32
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/experimental/metric_m2_reregister.py sweep --workers 30
python3 scripts/experimental/metric_m2_reregister.py report
