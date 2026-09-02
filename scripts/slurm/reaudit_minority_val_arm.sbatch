#!/bin/bash
#SBATCH -J rk_reval
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 D：一条估值口径回退臂的建带链。用法：
#   sbatch --job-name=rk_reval_<臂> scripts/slurm/reaudit_minority_val_arm.sbatch <臂> "<相对生产口径改了什么>"
# 产物落 data/processed/experiments/exp_reaudit_minority/val/<臂>/，末尾按 §12.30 重解买入线（只报数）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
ARM="$1"; EXTRA="$2"
S=data/processed
E=$S/experiments/exp_reaudit_minority/val/$ARM
mkdir -p "$E"

# §6.7 第 2 步生产建带口径，逐字对应；$EXTRA 追加在后，argparse 后者为准
COMMON="--all --value-model roic --roe-source onesided_max --roe-lift 2.0 --uniform-tier L2 \
  --since 2002-01-01 --roic-nopat-source conditional3 --roic-growth hybrid --roic-cycle-guard peak \
  --roic-cond-detect graded --roic-peak-ramp 0.3 --ttm-current on --growth-damp on --thin-equity-max 0.5 \
  --roic-trail-weight 0 --minority-basis earnings"

echo "=== [$(date +%T)] $ARM 建带（候选侧＋B2 并发；缺口文件各写各的）：$EXTRA ==="
# shellcheck disable=SC2086
RK_STMT_GAP_LOG="$E/gaps_base.csv" python3 scripts/build_historical_valuation_bands.py $COMMON $EXTRA \
  --out-bands "$E/roic_bands.csv" --out-daily "$E/roic_daily_raw.csv" > "$E/build_base.log" 2>&1 &
P1=$!
# shellcheck disable=SC2086
RK_STMT_GAP_LOG="$E/gaps_b2.csv" python3 scripts/build_historical_valuation_bands.py $COMMON $EXTRA \
  --ttm-trust on --ttm-trust-delta 0.02 \
  --out-bands "$E/roic_bands_b2.csv" --out-daily "$E/roic_daily_raw_b2.csv" > "$E/build_b2.log" 2>&1 &
P2=$!
wait $P1 $P2

echo "=== [$(date +%T)] $ARM 银行/保险股利折现覆盖（两侧）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 "$E/states_base.csv" "$E/roic_daily_raw.csv" "$E/roic_bands.csv" > "$E/bank_base.log" 2>&1 &
P3=$!
python3 scripts/rebuild_bank_bands.py divspread:0.02 "$E/states_b2.csv" "$E/roic_daily_raw_b2.csv" "$E/roic_bands_b2.csv" > "$E/bank_b2.log" 2>&1 &
P4=$!
wait $P3 $P4

echo "=== [$(date +%T)] $ARM 合成持仓侧逐日状态 ==="
python3 scripts/build_hold_daily_states.py --base "$E/states_base.csv" --b2 "$E/states_b2.csv" --out "$E/states_hold.csv"

echo "=== [$(date +%T)] $ARM 买入线重解到同一在册合格面（§12.30；在册 1.0454／边际 0.18）==="
python3 scripts/experimental/align_buy_line.py "$S/a_share_daily_states_adopted.csv" "$E/states_base.csv" \
  --base-line 1.0454 --swap-margin 0.18 | tee "$E/align_buy_line.txt"

rm -f "$E/roic_daily_raw.csv" "$E/roic_daily_raw_b2.csv"
echo "=== [$(date +%T)] $ARM 完成 ==="
