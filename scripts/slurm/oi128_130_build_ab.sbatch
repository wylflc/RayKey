#!/bin/bash
#SBATCH -J rk_oi128130
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 03:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128／129／130 采纳前置（轨道 A，用户裁定按原则采纳）：
#   PIT 臂 = OI-130 重述前版本按可得日选用 ＋ OI-129 主体重置触发登记（电投能源／中国神华）＋ 少数股东账面口径（旧）
#   NEW 臂 = PIT 臂 ＋ OI-128 少数股东扣减 max(账面, m×(EV−净金融负债))（新生产口径）
# 两臂各自重解买入线到同一在册合格面（§12.30），对现行 BASE 做 14 起点 × 两表 A/B；
# NEW 臂再做换仓边际 0.01 一档剂量扫描与信号层 P/V 分档前向回报。生产文件不动，落地另起作业。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi128_130_adopt
S=data/processed
mkdir -p "$EXP/configs"
COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on \
  --thin-equity-max 0.5 --roic-trail-weight 0"

echo "=== [$(date +%T)] 1/7 候选侧建带（PIT=book ｜ NEW=earnings，并行）==="
python3 scripts/build_historical_valuation_bands.py $COMMON --minority-basis book \
  --out-bands $S/roic_bands_pit.csv --out-daily $S/roic_daily_raw_pit.csv > "$EXP/build_pit.log" 2>&1 &
python3 scripts/build_historical_valuation_bands.py $COMMON --minority-basis earnings \
  --out-bands $S/roic_bands_new.csv --out-daily $S/roic_daily_raw_new.csv > "$EXP/build_new.log" 2>&1 &
wait
grep -h "重述前版本\|主体重置：\|逐日状态已写入" "$EXP/build_pit.log" "$EXP/build_new.log"

echo "=== [$(date +%T)] 2/7 B2 侧建带（并行）==="
python3 scripts/build_historical_valuation_bands.py $COMMON --minority-basis book --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $S/roic_bands_b2_pit.csv --out-daily $S/roic_daily_raw_b2_pit.csv > "$EXP/build_b2_pit.log" 2>&1 &
python3 scripts/build_historical_valuation_bands.py $COMMON --minority-basis earnings --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands $S/roic_bands_b2_new.csv --out-daily $S/roic_daily_raw_b2_new.csv > "$EXP/build_b2_new.log" 2>&1 &
wait

echo "=== [$(date +%T)] 3/7 银行/保险股利折现覆盖（四份，两两并行）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_pit.csv $S/roic_daily_raw_pit.csv $S/roic_bands_pit.csv > "$EXP/bank_pit.log" 2>&1 &
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_new.csv $S/roic_daily_raw_new.csv $S/roic_bands_new.csv > "$EXP/bank_new.log" 2>&1 &
wait
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_b2_pit.csv $S/roic_daily_raw_b2_pit.csv $S/roic_bands_b2_pit.csv > "$EXP/bank_b2_pit.log" 2>&1 &
python3 scripts/rebuild_bank_bands.py divspread:0.02 $S/a_share_daily_states_b2_new.csv $S/roic_daily_raw_b2_new.csv $S/roic_bands_b2_new.csv > "$EXP/bank_b2_new.log" 2>&1 &
wait
tail -n 3 "$EXP"/bank_*.log

echo "=== [$(date +%T)] 4/7 合成持仓侧逐日状态（并行）==="
python3 scripts/build_hold_daily_states.py --base $S/a_share_daily_states_pit.csv --b2 $S/a_share_daily_states_b2_pit.csv --out $S/a_share_daily_states_hold_pit.csv > "$EXP/hold_pit.log" 2>&1 &
python3 scripts/build_hold_daily_states.py --base $S/a_share_daily_states_new.csv --b2 $S/a_share_daily_states_b2_new.csv --out $S/a_share_daily_states_hold_new.csv > "$EXP/hold_new.log" 2>&1 &
wait

echo "=== [$(date +%T)] 5/7 买入线重解（§12.30，各臂对现行 1.0138 的合格面）==="
python3 scripts/experimental/align_buy_line.py $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_pit.csv \
  --base-line 1.0138 --swap-margin 0.18 | tee "$EXP/align_pit.txt"
WP=$(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_pit.txt" | tail -1)
python3 scripts/experimental/align_buy_line.py $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_new.csv \
  --base-line 1.0138 --swap-margin 0.18 | tee "$EXP/align_new.txt"
WN=$(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_new.txt" | tail -1)
echo "重解买入线：PIT --width $WP ｜ NEW --width $WN"
[ -n "$WP" ] && [ -n "$WN" ] || { echo "买入线重解失败，停止"; exit 1; }

STP="--daily-states $S/a_share_daily_states_pit.csv --hold-states $S/a_share_daily_states_hold_pit.csv"
STN="--daily-states $S/a_share_daily_states_new.csv --hold-states $S/a_share_daily_states_hold_new.csv"
cat > "$EXP/configs/adopt_arms.txt" <<CFG
# OI-128/129/130：PIT = 重述版本＋主体重置触发（账面少数股东）；NEW = PIT ＋ 少数股东盈利份额扣减。买入线各自重解，换仓边际 0.18 不动。
BASE|
PIT|$STP --width $WP
NEW|$STN --width $WN
CFG
{
  echo "# NEW 臂换仓边际剂量扫描（§12.1 第 4 款①），买入线固定重解值 --width $WN"
  echo "BASE|"
  for m in 0.10 0.12 0.13 0.14 0.15 0.16 0.17 0.18 0.19 0.20 0.22 0.25; do
    echo "NEW_M${m#0.}|$STN --width $WN --swap-margin $m"
  done
} > "$EXP/configs/margin_arms.txt"

echo "=== [$(date +%T)] 6/7 14 起点 × 两表 A/B（三臂）＋ NEW 臂换仓边际剂量扫描 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/adopt_arms.txt" --out "$EXP/sweep_adopt.txt" --workers 28 \
  --title "OI-128/129/130 采纳臂：PIT（重述版本＋主体重置触发）与 NEW（＋少数股东盈利份额扣减），买入线各自重解" \
  | tee "$EXP/report_adopt.txt"
python3 scripts/sweep_backtest_configs.py "$EXP/configs/margin_arms.txt" --out "$EXP/sweep_margin.txt" --workers 28 \
  --title "OI-128/129/130 NEW 臂换仓边际剂量（买入线固定重解值）" | tee "$EXP/report_margin.txt"

echo "=== [$(date +%T)] 7/7 信号层 P/V 分档前向回报（NEW，剔除银行，与 exp_oi128_minority/tier_forward_adopted.txt 同口径）==="
python3 scripts/experimental/panel_tier_forward.py --states $S/a_share_daily_states_new.csv \
  --panel $S/pit_attention/panel_moat_bank_v6b.csv --since 2005-01-01 --exclude-banks \
  --per-code-out "$EXP/tier_forward_percode_new.csv" | tee "$EXP/tier_forward_new.txt"
echo "=== [$(date +%T)] 完成 ==="
