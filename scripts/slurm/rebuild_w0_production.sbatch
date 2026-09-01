#!/bin/bash
#SBATCH -J rk_w0_chain
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §6.7 第 2~3 步，全市场，`--roic-trail-weight 0`（OI-124：W=0 转生产基准）。
# 产物先落 *_w0 暂存名，核对后再换入生产文件名；现行 W=1.0 的四份留作 *_w100.bak，可回滚。
# 实测串行耗时：建带 8:05 + B2 7:29 + 银行覆盖 2×2:45 + 合成持仓侧 2:32 ≈ 24 分钟。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
P=data/processed

COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
 --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid \
 --roic-cycle-guard peak --roic-cond-detect graded --roic-peak-ramp 0.3 \
 --ttm-current on --growth-damp on --thin-equity-max 0.5 --roic-trail-weight 0"

echo "=== [$(date +%T)] 第 2 步 候选侧建带 ==="
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands $P/roic_bands_w0.csv --out-daily $P/roic_daily_raw_w0.csv

echo "=== [$(date +%T)] 第 2b 步 B2 建带（与第 2 步串行）==="
python3 scripts/build_historical_valuation_bands.py $COMMON --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $P/roic_bands_b2_w0.csv --out-daily $P/roic_daily_raw_b2_w0.csv

echo "=== [$(date +%T)] 第 3 步 银行/保险股利折现覆盖（两侧）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $P/a_share_daily_states_adopted_w0.csv $P/roic_daily_raw_w0.csv $P/roic_bands_w0.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $P/a_share_daily_states_b2_w0.csv $P/roic_daily_raw_b2_w0.csv $P/roic_bands_b2_w0.csv

echo "=== [$(date +%T)] 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py \
  --base $P/a_share_daily_states_adopted_w0.csv \
  --b2   $P/a_share_daily_states_b2_w0.csv \
  --out  $P/a_share_daily_states_hold_w0.csv

echo "=== [$(date +%T)] 买入线重解到在册合格面 17.777% ==="
python3 scripts/experimental/align_buy_line.py \
  $P/a_share_daily_states_adopted.csv $P/a_share_daily_states_adopted_w0.csv \
  --base-line 0.9343 --swap-margin 0.19

echo "=== [$(date +%T)] 完成 ==="
ls -la $P/*_w0.csv
