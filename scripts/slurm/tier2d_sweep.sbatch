#!/bin/bash
#SBATCH -J rk_tier2d
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.177 表 C：买入一档 × 卖出一档的二维档位粗扫（--x × --sell-x，2.5／5／7.5／10%，15 臂＋BASE），14 起点两遍。
# 以 afterany 依赖挂在表 A2 作业之后（BASE 臂 summary 文件名相同，不可并行）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_ladder_pairswap
echo "=== [$(date +%T)] 表 C（$(grep -c '|' "$EXP/configs/tier2d_base.txt") 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/tier2d_base.txt" \
  --out "$EXP/sweep_tier2d.txt" --workers 60 \
  --title "§12.177 表 C 买入档 × 卖出档" | tee "$EXP/report_tier2d.txt"
echo "=== [$(date +%T)] 完成 ==="
