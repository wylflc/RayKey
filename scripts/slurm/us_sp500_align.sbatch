#!/bin/bash
#SBATCH -J us_sp500_align
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 P4 对齐臂：把买入线对齐到 A 股在册合格面（候选侧下侧比例），换仓边际同倍缩放
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/experimental/align_buy_line.py data/processed/a_share_daily_states_adopted.csv data/processed/us_daily_states_adopted.csv \
  --base-line 1.0454 --swap-margin 0.15 \
  --base-panel data/processed/pit_attention/panel_moat_bank_v6b.csv --panel data/processed/pit_attention/panel_sp500_us.csv
