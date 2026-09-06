#!/bin/bash
#SBATCH -J us_sp500_tierfwd
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 辅助：美股候选侧状态上的 P/V 分档前向回报（OI-150 分档表）
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/experimental/panel_tier_forward.py --states data/processed/us_daily_states_adopted.csv \
  --panel data/processed/pit_attention/panel_sp500_us.csv --since 2012-05-01 \
  --ohlcv-dir data/raw/ohlcv_us --actions data/raw/corporate_actions/us_corporate_actions.csv \
  > data/experiments/exp_us_sp500_port/tier_forward_us.txt
