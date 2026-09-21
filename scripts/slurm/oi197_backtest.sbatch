#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:35:00
#SBATCH --job-name=oi197_bt
#SBATCH --output=logs/oi197_bt_%j.out
#SBATCH --error=logs/oi197_bt_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
/usr/bin/time -v python3 data/experiments/exp_oi197_20260921/assemble.py
/usr/bin/time -v python3 data/experiments/exp_oi197_20260921/run.py
/usr/bin/time -v python3 data/experiments/exp_oi197_20260921/analyze.py
