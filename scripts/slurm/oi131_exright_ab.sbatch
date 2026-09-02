#!/bin/bash
#SBATCH -J rk_oi131
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-131 轨道 A（缺陷修正）：银行/保险股利折现覆盖补除权调整。
# ROIC 带未变，故只重跑 §6.7 第 3~4 步；产物写 *_fix，生产文件不动。
# 两条候选臂：FIXALIGN = 买入线按 §12.30 重解；FIXASIS = 沿用在册 0.9976。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi131_exright
S=data/processed

echo "=== [$(date +%T)] 1/4 银行覆盖（候选侧）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $S/a_share_daily_states_fix.csv $S/roic_daily_raw.csv $S/roic_bands.csv
echo "=== [$(date +%T)] 2/4 银行覆盖（B2 侧）==="
python3 scripts/rebuild_bank_bands.py divspread:0.02 \
  $S/a_share_daily_states_b2_fix.csv $S/roic_daily_raw_b2.csv $S/roic_bands_b2.csv
echo "=== [$(date +%T)] 3/4 合成持仓侧 ==="
python3 scripts/build_hold_daily_states.py \
  --base $S/a_share_daily_states_fix.csv --b2 $S/a_share_daily_states_b2_fix.csv \
  --out $S/a_share_daily_states_hold_fix.csv

echo "=== [$(date +%T)] 4/4 买入线重解 + 14 起点 × 两遍 A/B ==="
python3 scripts/experimental/align_buy_line.py \
  $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_fix.csv \
  --base-line 0.9976 --swap-margin 0.18 | tee "$EXP/align_buy_line.txt"
WIDTH=$(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_buy_line.txt" | tail -1)
echo "重解买入线 --width $WIDTH"
[ -n "$WIDTH" ] || { echo "买入线重解失败，停止"; exit 1; }

ST="--daily-states $S/a_share_daily_states_fix.csv --hold-states $S/a_share_daily_states_hold_fix.csv"
cat > "$EXP/configs/exright_arms.txt" <<CFG
# OI-131：银行覆盖补除权调整。FIXALIGN 买入线按 §12.30 重解；FIXASIS 沿用在册 0.9976。换仓边际两臂都不动。
BASE|
FIXALIGN|$ST --width $WIDTH
FIXASIS|$ST --width 0.0024
CFG

python3 scripts/sweep_backtest_configs.py "$EXP/configs/exright_arms.txt" \
  --out "$EXP/sweep_exright.txt" --workers 28 \
  --title "OI-131 银行股利折现覆盖补除权调整（轨道 A 缺陷修正）" \
  | tee "$EXP/report_exright.txt"
echo "=== [$(date +%T)] 完成 ==="
