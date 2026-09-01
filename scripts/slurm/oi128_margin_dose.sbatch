#!/bin/bash
#SBATCH -J rk_oi128md
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-128 第二轮：换仓边际在 MINEARN 臂上按 0.01 一档重新剂量扫描（§12.1 第 4 款①，
# 「换仓边际不随买入线缩放，按 0.01 一档的剂量扫描重定」）。第一轮沿用 BASE 的 0.18，
# 而买入线由 0.9976 重解到 1.0278（标度移 3.0%，为 §6.7 第 7 步在册容差 ±0.01 的 3 倍）。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi128_minority

echo "=== [$(date +%T)] 换仓边际剂量扫描（13 臂 + 1 诊断臂）× 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/margin_arms.txt" \
  --out "$EXP/sweep_margin.txt" --workers 28 \
  --title "OI-128 MINEARN 臂换仓边际剂量（买入线固定重解值 1.0278）" \
  | tee "$EXP/report_margin.txt"
echo "=== [$(date +%T)] 完成 ==="
