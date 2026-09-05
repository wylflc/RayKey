#!/bin/bash
#SBATCH -J rk_oi110
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-110 删除估值减持线的护栏 A/B（§12.1 轨道 A）。
# 23 起点 × 2 臂 × 两遍（全样本＋去赢家）= 92 次运行。
# 单次回测实测约 1.5 分钟、峰值 1.49 GB；--workers 24 ≈ 36 GB，低于 -n 32 的 56 GB。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_oi110_sellline

echo "=== [$(date +%H:%M:%S)] 23 起点 × 2 臂 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/sellline_arms.txt" \
  --out "$EXP/sweep_sellline.txt" \
  --workers 24 \
  --title "删除估值减持线（OI-110，轨道 A 护栏）" \
  | tee "$EXP/sweep_sellline_report.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
