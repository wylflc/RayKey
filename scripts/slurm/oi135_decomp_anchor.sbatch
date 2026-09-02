#!/bin/bash
#SBATCH -J rk_oi135
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.172 表 L（GUARDEFF 单变量拆解阶梯的 14 起点两遍 A/B）＋ 表 M（§12.67 锚点关卡重跑）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_reaudit_minority
V=$EXP/val
CFG=$EXP/configs/guard_decomp.txt

{
  echo "# §12.172 表 L：GUARDEFF 拆解阶梯。买入线各臂重解到同一在册合格面，换仓边际一律 0.18。"
  echo "BASE|"
  for arm in GE_TROUGHOFF RAMP0 GE_BINARY GUARDEFF GE_EFF25 GE_EFF45 PEAKK14 PEAKK18; do
    d=$V/$arm
    [ -f "$d/states_base.csv" ] && [ -f "$d/states_hold.csv" ] || { echo "# $arm 产物缺失，跳过"; continue; }
    w=$(grep -oP '`--width \K-?[0-9.]+' "$d/align_buy_line.txt" 2>/dev/null | tail -1)
    [ -n "$w" ] || { echo "# $arm 买入线重解失败，跳过"; continue; }
    echo "$arm|--daily-states $d/states_base.csv --hold-states $d/states_hold.csv --width $w"
  done
} > "$CFG"
cat "$CFG"

echo "=== [$(date +%T)] 表 L：拆解阶梯 A/B ==="
python3 scripts/sweep_backtest_configs.py "$CFG" \
  --out "$EXP/sweep_decomp.txt" --workers 60 \
  --title "§12.172 表 L GUARDEFF 单变量拆解阶梯（买入线各自重解）" | tee "$EXP/report_decomp.txt"

echo "=== [$(date +%T)] 表 M：§12.67 锚点关卡重跑 ==="
: > "$EXP/anchor_gate.txt"
for a in "BASE:data/processed/roic_bands.csv" \
         "GE_TROUGHOFF:$V/GE_TROUGHOFF/roic_bands.csv" \
         "RAMP0:$V/RAMP0/roic_bands.csv" \
         "GE_BINARY:$V/GE_BINARY/roic_bands.csv" \
         "GUARDEFF:$V/GUARDEFF/roic_bands.csv" \
         "GE_EFF25:$V/GE_EFF25/roic_bands.csv" \
         "GE_EFF45:$V/GE_EFF45/roic_bands.csv" \
         "PEAKK14:$V/PEAKK14/roic_bands.csv" \
         "PEAKK18:$V/PEAKK18/roic_bands.csv"; do
  tag=${a%%:*}; bands=${a##*:}
  [ -f "$bands" ] || { echo "$tag: 带文件缺失 $bands" | tee -a "$EXP/anchor_gate.txt"; continue; }
  echo "----- $tag -----" >> "$EXP/anchor_gate.txt"
  python3 scripts/experimental/roic_anchor_check.py --bands "$bands" --tag "$tag" >> "$EXP/anchor_gate.txt" 2>&1
done
grep -E '^----- |配对正确率|读错' "$EXP/anchor_gate.txt"
echo "=== [$(date +%T)] 完成 ==="
