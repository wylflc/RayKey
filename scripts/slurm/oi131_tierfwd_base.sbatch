#!/bin/bash
#SBATCH -J rk_oi131tf
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-131：修正臂的信号层跑的是**含银行**口径（本条只动银行，剔除银行就看不到效果），
# 故 BASE 侧须用同一口径重跑一遍才可比。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi131_exright
python3 scripts/experimental/panel_tier_forward.py \
  --states data/processed/a_share_daily_states_adopted.csv \
  --panel data/processed/pit_attention/panel_moat_bank_v6b.csv --since 2005-01-01 \
  | tee "$EXP/tier_forward_base_withbanks.txt"
echo "=== 完成 ==="
