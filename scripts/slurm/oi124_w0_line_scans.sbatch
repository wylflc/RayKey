#!/bin/bash
#SBATCH -J rk_w0_scans
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-124：`W=0` 转基准后重定两条线。三个单旋钮剂量扫描，各自 BASE 行 = 换基准后的生产在册值。
# 换仓阈值 21 档 × 14 起点 × 两遍 = 588；单票上限 17 档 = 476；授信 14 档 = 392。合计 1,456 次运行。
# **前置**：生产逐日状态已换成 W=0 链，且 sweep_backtest_configs.BASE 的 --width 已改成重解值。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi124_w0base

for s in margin poscap credit; do
  echo "=== [$(date +%T)] $s ==="
  python3 scripts/sweep_backtest_configs.py "$EXP/configs/${s}_arms.txt" \
    --out "$EXP/sweep_${s}.txt" --workers 48 \
    --title "OI-124 ${s} 剂量扫描（W=0 基准，14 起点标准链）" \
    | tee "$EXP/report_${s}.txt"
done

echo "=== [$(date +%T)] 完成 ==="
