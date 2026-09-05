#!/bin/bash
#SBATCH -J rk_reaudit
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 少数股东纪元下历代采纳项的全面重扫。表 A = 操作规则逐项回退，表 B = 策略参数剂量。
# 逐日状态、宇宙、两条线全部沿用当前生产 BASE，不重建带、不重解买入线。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_reaudit_minority

echo "=== [$(date +%T)] 表 A：操作规则逐项回退（25 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/rules_revert.txt" \
  --out "$EXP/sweep_rules.txt" --workers 60 \
  --title "§12.171 表 A 历代采纳的操作规则在 OI-128 纪元上的逐项回退" \
  | tee "$EXP/report_rules.txt"

echo "=== [$(date +%T)] 表 B：策略参数剂量重扫（24 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/param_dose.txt" \
  --out "$EXP/sweep_params.txt" --workers 60 \
  --title "§12.171 表 B 策略参数在 OI-128 纪元上的剂量重扫" \
  | tee "$EXP/report_params.txt"

echo "=== [$(date +%T)] 完成 ==="
