#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=32
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:30:00
#SBATCH --job-name=oi198_bt
#SBATCH --output=logs/oi198_bt_%j.out
#SBATCH --error=logs/oi198_bt_%j.err
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/assemble.py
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/current.py
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/run.py
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/analyze.py
/usr/bin/time -v python3 data/experiments/exp_oi198_20260921/diagnostics.py
