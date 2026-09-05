#!/bin/bash
#SBATCH -J rk_oi128sw
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128 续跑：第 1~4 步产物已在盘（job 26300498），本作业只做第 5~6 步。
# 买入线按 §12.30 重解为 1.0278（--width -0.0278）；**换仓边际保持 BASE 的 0.18**
# ——§12.1「换仓边际不随买入线缩放，按 0.01 一档剂量扫描重定」，剂量扫描属采纳前置，不在护栏轮内。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi128_minority
S=data/processed
mkdir -p "$EXP/configs"

python3 scripts/experimental/align_buy_line.py \
  $S/a_share_daily_states_adopted.csv $S/a_share_daily_states_mi.csv \
  --base-line 0.9976 --swap-margin 0.18 | tee "$EXP/align_buy_line.txt"
WIDTH=$(grep -oP '`--width \K-?[0-9.]+' "$EXP/align_buy_line.txt" | tail -1)
echo "重解买入线 --width $WIDTH"
[ -n "$WIDTH" ] || { echo "买入线重解失败，停止"; exit 1; }

cat > "$EXP/configs/minority_arms.txt" <<CFG
# OI-128：少数股东扣减口径 A/B（轨道 A 护栏轮）。两侧逐日状态与重解买入线一并给全，换仓边际不动。
BASE|
MINEARN|--daily-states $S/a_share_daily_states_mi.csv --hold-states $S/a_share_daily_states_hold_mi.csv --width $WIDTH
CFG

echo "=== [$(date +%T)] 14 起点 × 两遍 A/B ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/minority_arms.txt" \
  --out "$EXP/sweep_minority.txt" --workers 28 \
  --title "OI-128 少数股东扣减口径（账面 → max(账面, m×权益价值)），买入线重解 1.0278" \
  | tee "$EXP/report_minority.txt"
echo "=== [$(date +%T)] 完成 ==="
