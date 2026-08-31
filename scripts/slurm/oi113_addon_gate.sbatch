#!/bin/bash
#SBATCH -J rk_oi113
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-113 加仓走势闸门收紧的 A/B：加仓由 `MA20>MA60` 收到与新建仓同条件 `收盘>MA20>MA60`
# （BASE 的 --addon-trend ma-only → full）。23 起点 × 2 臂 × 两遍（全样本＋去赢家）= 92 次运行。
# 单次回测实测约 1.5 分钟、峰值 1.49 GB；--workers 24 ≈ 36 GB，低于 -n 32 的 56 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/processed/experiments/exp_oi113_addon_gate

echo "=== [$(date +%H:%M:%S)] 23 起点 × 2 臂 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/addon_arms.txt" \
  --out "$EXP/sweep_addon.txt" \
  --workers 24 \
  --title "加仓闸门收紧为 收盘>MA20>MA60（OI-113）" \
  | tee "$EXP/sweep_addon_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
