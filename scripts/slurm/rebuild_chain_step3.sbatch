#!/bin/bash
#SBATCH -J rk_step3
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §6.7 第 3 步单独重跑（第 2/2b 步产物已在盘上时用）：银行/保险股利折现覆盖 → 两侧
# 采纳逐日状态 → 合成持仓侧逐日状态。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

for f in roic_bands.csv roic_daily_raw.csv roic_bands_b2.csv roic_daily_raw_b2.csv; do
  [ -s "data/processed/$f" ] || { echo "缺少前置产物 data/processed/$f，请先跑第 2/2b 步" >&2; exit 1; }
done

echo "=== [$(date +%H:%M:%S)] 候选侧股利折现覆盖 ==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_adopted.csv \
  data/processed/roic_daily_raw.csv \
  data/processed/roic_bands.csv

echo "=== [$(date +%H:%M:%S)] B2 侧股利折现覆盖 ==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_b2.csv \
  data/processed/roic_daily_raw_b2.csv \
  data/processed/roic_bands_b2.csv

echo "=== [$(date +%H:%M:%S)] 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py

echo "=== [$(date +%H:%M:%S)] 完成 ==="
ls -la data/processed/a_share_daily_states_adopted.csv \
       data/processed/a_share_daily_states_b2.csv \
       data/processed/a_share_daily_states_hold.csv
