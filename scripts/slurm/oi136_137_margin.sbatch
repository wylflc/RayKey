#!/bin/bash
#SBATCH -J rk_o136m
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 05:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.174 表 R：OI-136（--max-corr 1.0）／OI-137（G110U）／两者组合 各自的换仓边际 0.10~0.30 重扫（§12.1 第 4 款①）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi136_137
for a in c100 g110u combo; do
  echo "=== [$(date +%T)] 表 R·$a：换仓边际重扫（21 臂 × 14 起点 × 两遍）==="
  python3 scripts/sweep_backtest_configs.py "$EXP/configs/${a}_margin.txt" \
    --out "$EXP/sweep_margin_$a.txt" --workers 60 \
    --title "§12.174 表 R·$a 换仓边际（对照＝该臂 × 0.18）" | tee "$EXP/report_margin_$a.txt"
done
echo "=== [$(date +%T)] 完成 ==="
