#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi207_h2r
#SBATCH --output=logs/oi207_h2r_%j.out
#SBATCH --error=logs/oi207_h2r_%j.err
# OI-207 H2：回测已完成，只重出读数（第 13 款、第 11 款、当前银行）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi207_h2_20260928
python3 -c "import json, run; m = json.load(open('run_manifest.json')); run.readings(m['A'], m['U'])"
