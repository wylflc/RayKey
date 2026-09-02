#!/bin/bash
#SBATCH -J rk_oi120
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-120 轨道 A（机制修复）：§9.3.3 比例冷却计数器买入侧与卖出侧分开计数。
# BASE 臂按旧口径（--lot-cooldown-shared，须与在册读数逐位相同）；SPLIT 臂为引擎新缺省（不带开关）。
# 逐日状态、买入线、换仓边际全部沿用 BASE，不重解。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi120_cooldown
mkdir -p "$EXP/configs"

cat > "$EXP/configs/split_arms.txt" <<CFG
# OI-120：§9.3.3 冷却计数器买卖分侧。BASE = 旧口径（买卖共用一个计数器）；SPLIT = 买入侧与卖出侧各自计数（引擎缺省）。
BASE|--lot-cooldown-shared
SPLIT|
CFG

echo "=== [$(date +%T)] 14 起点 × 两臂 × 两遍（全样本＋去赢家 A）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/split_arms.txt" \
  --out "$EXP/sweep_split.txt" --workers 28 \
  --title "OI-120 §9.3.3 冷却计数器买入侧与卖出侧分开计数（轨道 A 机制修复）" \
  | tee "$EXP/report_split.txt"
echo "=== [$(date +%T)] 完成 ==="
