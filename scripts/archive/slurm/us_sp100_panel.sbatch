#!/bin/bash
#SBATCH -J us_sp100_panel
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 追加读数：标普 100 历史成分面板（Wikipedia 修订历史 → 区间 → 标普 500 成员表取 CIK）
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
python3 scripts/build_us_sp100_panel.py
