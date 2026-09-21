#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:40:00
#SBATCH --job-name=oi196_states
#SBATCH --output=logs/oi196_states_%j.out
#SBATCH --error=logs/oi196_states_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
/usr/bin/time -v python3 data/experiments/exp_oi196_20260921/prepare.py
/usr/bin/time -v python3 data/experiments/exp_oi196_20260921/build.py
