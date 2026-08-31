#!/bin/bash
#SBATCH -J rk_rebuild
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §6.7 估值重建链的第 2 / 2b / 3 步：从已迁移的财务与行情输入重建逐日估值状态。
# 不含第 1 步（抓取）——迁移后首次重建刻意沿用 Mac 带过来的输入，
# 好让产出读数能与 §12.1 在册基准逐位对照，作为迁移的端到端校验。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5"

echo "=== [$(date +%H:%M:%S)] 第 2 步：候选侧建带 ==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands data/processed/roic_bands.csv \
  --out-daily data/processed/roic_daily_raw.csv

echo "=== [$(date +%H:%M:%S)] 第 2b 步：B2 建带（与第 2 步串行）==="
# shellcheck disable=SC2086
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands data/processed/roic_bands_b2.csv \
  --out-daily data/processed/roic_daily_raw_b2.csv

echo "=== [$(date +%H:%M:%S)] 第 3 步：银行/保险股利折现覆盖 ==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_adopted.csv \
  data/processed/roic_daily_raw.csv \
  data/processed/roic_bands.csv

python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  data/processed/a_share_daily_states_b2.csv \
  data/processed/roic_daily_raw_b2.csv \
  data/processed/roic_bands_b2.csv

echo "=== [$(date +%H:%M:%S)] 第 3 步末：合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py

echo "=== [$(date +%H:%M:%S)] 完成，产物： ==="
ls -la data/processed/roic_bands.csv data/processed/roic_daily_raw.csv \
       data/processed/roic_bands_b2.csv data/processed/roic_daily_raw_b2.csv \
       data/processed/a_share_daily_states_adopted.csv \
       data/processed/a_share_daily_states_b2.csv \
       data/processed/a_share_daily_states_hold.csv
