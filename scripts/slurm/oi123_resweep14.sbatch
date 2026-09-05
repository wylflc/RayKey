#!/bin/bash
#SBATCH -J rk_oi123r14
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-123 裁定读数：§12.155 增速腿剂量家族按 v4.117 标准起点集（路径 ≥10 年，14 个）重扫标准链。
# 配置照用 exp_oi115_trailleg/configs/trail_arms.txt（BASE + TW000/025/050/075/125 + 诊断臂 TW000S，
# 各臂逐日状态与对齐买入线不变），7 臂 × 14 起点 × 全样本＋去赢家 = 196 次运行。
# --workers 48 ≈ 72 GB < -n 64 的 112 GB；23 起点同配置实测 7 分 34 秒（作业 26273155），本轮更小。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_oi115_trailleg

python3 scripts/sweep_backtest_configs.py "$EXP/configs/trail_arms.txt" \
  --out "$EXP/sweep_trailleg_14.txt" \
  --workers 48 \
  --title "① 利润增速腿权重剂量臂（OI-123 裁定读数，14 起点标准链 v4.117）" \
  | tee "$EXP/report_trailleg_14.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
