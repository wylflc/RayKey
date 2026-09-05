#!/bin/bash
#SBATCH -J rk_rebase018
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-124 收口：① §6.7 第 7 步 换仓边际标度漂移守卫（两套逐日状态重建后必跑）；
# ② 新在册基准（W=0 ＋ 买入线 0.9976 ＋ 换仓边际 0.18）单臂 14 起点 × 两遍重扫，
#    去赢家名单按新 BASE 自身前五重选。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi124_w0base

echo "=== [$(date +%T)] §6.7 第 7 步 换仓边际标度漂移守卫 ==="
python3 scripts/check_swap_margin_scale_drift.py || echo "（守卫返回非零，读上文判断是否需重扫）"

echo "=== [$(date +%T)] 新在册基准单臂重扫 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/base_only.txt" \
  --out "$EXP/sweep_base_m018.txt" --workers 28 \
  --title "OI-124 新在册基准（W=0／买入线 0.9976／换仓边际 0.18）" \
  | tee "$EXP/report_base_m018.txt"

echo "=== [$(date +%T)] 完成 ==="
