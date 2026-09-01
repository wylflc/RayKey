#!/bin/bash
#SBATCH -J rk_oi128mi
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128 轨道 A（机制修复）：股权桥的少数股东扣减由「账面」改为「账面与按盈利份额分得的
# 权益价值取较大者」。换估值口径 → 全链重建两侧逐日状态 → 买入线重解到同一在册合格面
# （§12.30 / align_buy_line.py）→ 14 起点 × 两遍 A/B。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi128_minority
S=data/processed
COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on \
  --thin-equity-max 0.5 --roic-trail-weight 0 --minority-basis earnings"

echo "=== [$(date +%T)] 1/6 候选侧建带（minority-basis earnings）==="
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --out-bands $S/roic_bands_mi.csv --out-daily $S/roic_daily_raw_mi.csv

echo "=== [$(date +%T)] 2/6 B2 侧建带 ==="
python3 scripts/build_historical_valuation_bands.py $COMMON \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $S/roic_bands_b2_mi.csv --out-daily $S/roic_daily_raw_b2_mi.csv

echo "=== [$(date +%T)] 3/6 银行/保险股利折现覆盖（两侧）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $S/a_share_daily_states_mi.csv $S/roic_daily_raw_mi.csv $S/roic_bands_mi.csv
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $S/a_share_daily_states_b2_mi.csv $S/roic_daily_raw_b2_mi.csv $S/roic_bands_b2_mi.csv

echo "=== [$(date +%T)] 4/6 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py \
  --base $S/a_share_daily_states_mi.csv --b2 $S/a_share_daily_states_b2_mi.csv \
  --out $S/a_share_daily_states_hold_mi.csv

echo "=== [$(date +%T)] 5/6 买入线重解到同一在册合格面（§12.30）==="
python3 scripts/experimental/align_buy_line.py \
  $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_mi.csv \
  --base-line 0.9976 --swap-margin 0.18 | tee "$EXP/align_buy_line.txt"

WIDTH=$(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_buy_line.txt" | tail -1)   # 口径整体平移可解出负半宽（买入线 > 1）
echo "重解买入线 --width $WIDTH"
[ -n "$WIDTH" ] || { echo "买入线重解失败，停止"; exit 1; }

cat > "$EXP/configs/minority_arms.txt" <<CFG
# OI-128：少数股东扣减口径 A/B。MINEARN 的两侧逐日状态与重解买入线一并给全。
BASE|
MINEARN|--daily-states $S/a_share_daily_states_mi.csv --hold-states $S/a_share_daily_states_hold_mi.csv --width $WIDTH
CFG

echo "=== [$(date +%T)] 6/6 14 起点 × 两遍 A/B ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/minority_arms.txt" \
  --out "$EXP/sweep_minority.txt" --workers 28 \
  --title "OI-128 少数股东扣减口径（账面 → max(账面, m×权益价值)）" \
  | tee "$EXP/report_minority.txt"

echo "=== [$(date +%T)] 完成 ==="
