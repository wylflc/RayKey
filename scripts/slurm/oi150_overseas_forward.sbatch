#!/bin/bash
#SBATCH -J rk_oi150
#SBATCH -p rome
#SBATCH -A tes21035
#SBATCH -n 16
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# Compatibility entry for the frozen original sample and audited completion runner.
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/experimental/oi150_complete.py prepare --fetch
python3 scripts/experimental/oi150_complete.py value --workers 16
python3 scripts/experimental/oi150_complete.py report
