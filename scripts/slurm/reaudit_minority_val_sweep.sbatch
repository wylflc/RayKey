#!/bin/bash
#SBATCH -J rk_revsweep
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 D：11 条估值口径回退臂的 14 起点两遍 A/B。
# 每臂的两侧逐日状态来自 reaudit_minority_val_arm.sbatch，买入线取该臂 align_buy_line.txt 的重解值
# （§12.30：换口径必须重解到同一在册合格面，否则比的是两条不同宽度的闸门）。换仓边际一律沿用 0.18。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_reaudit_minority
V=$EXP/val
CFG=$EXP/configs/val_revert.txt

{
  echo "# §12.171 表 D：估值口径逐项回退臂（轨道 B）。买入线各臂重解到同一在册合格面，换仓边际沿用 0.18。"
  echo "BASE|"
  for d in "$V"/*/; do
    arm=$(basename "$d")
    [ -f "$d/states_base.csv" ] && [ -f "$d/states_hold.csv" ] || { echo "# $arm 产物缺失，跳过"; continue; }
    w=$(grep -oP '`--width \K-?[0-9.]+' "$d/align_buy_line.txt" 2>/dev/null | tail -1)
    [ -n "$w" ] || { echo "# $arm 买入线重解失败，跳过"; continue; }
    echo "$arm|--daily-states $d/states_base.csv --hold-states $d/states_hold.csv --width $w"
  done
} > "$CFG"
cat "$CFG"

echo "=== [$(date +%T)] 表 D：估值口径回退臂 A/B ==="
python3 scripts/sweep_backtest_configs.py "$CFG" \
  --out "$EXP/sweep_val.txt" --workers 60 \
  --title "§12.171 表 D 历代采纳的估值口径在 OI-128 纪元上的逐项回退（买入线各自重解）" \
  | tee "$EXP/report_val.txt"
echo "=== [$(date +%T)] 完成 ==="
