#!/bin/bash
#SBATCH --account=tes21035
#SBATCH --partition=rome
#SBATCH --cpus-per-task=16
#SBATCH --mem-per-cpu=1792M
#SBATCH --time=00:45:00
#SBATCH --job-name=oi215_reparse
#SBATCH --output=logs/oi215_reparse_%j.out
#SBATCH --error=logs/oi215_reparse_%j.err
# OI-215 候选解析规则 R1/R2：缓存年报文本全量重解析到实验目录（不写生产 cash_note_items.csv）
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey/data/experiments/exp_oi215_notes_20260925
/usr/bin/time -v python3 reparse.py
