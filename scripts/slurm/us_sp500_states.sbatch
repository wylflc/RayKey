#!/bin/bash
#SBATCH -J us_sp500_states
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 P2：逐次申报时点估值 → 逐日状态（候选侧）；第一期持仓侧 = 候选侧（复制一份）
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
python3 scripts/build_us_daily_states.py --workers 16 || exit 1
cp data/processed/us_daily_states_adopted.csv data/processed/us_daily_states_hold.csv
ls -la data/processed/us_daily_states_*.csv
