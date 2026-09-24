#!/bin/bash
#SBATCH -J oi205_an
#SBATCH -A tes21035
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH --mem-per-cpu=1792M
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-205 回测收尾：run.py 已完成（27123975，输入摘要变化经 input_change_audit.json 核定在回测末日之后）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
cd data/experiments/exp_oi205_20260924
python3 analyze.py
python3 diagnostics.py
python3 current.py
