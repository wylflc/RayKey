#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=01:00:00
#SBATCH --job-name=audit2010
#SBATCH --output=logs/audit2010_%j.out
#SBATCH --error=logs/audit2010_%j.err
# 2010 年前后回测买入候选核查：流式摘录逐日状态（2 GB），财务数据对年报原文，入选时估值（data/experiments/exp_audit_2010_candidates_20261001/）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_audit_2010_candidates_20261001
/usr/bin/time -v python3 audit.py
