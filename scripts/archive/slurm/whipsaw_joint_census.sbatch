#!/bin/bash
#SBATCH -J rk_whjcnt
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 00:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/experimental/whipsaw_joint_census.py
