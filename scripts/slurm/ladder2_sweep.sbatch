#!/bin/bash
#SBATCH -J rk_ladder2
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.177 表 A2：高阈值阶梯涨幅减持（--gain-ladder，49 臂＋BASE），14 起点两遍。
# 以 afterany 依赖挂在表 A／B 作业之后——BASE 臂 summary 文件名相同，不可与另一份扫描并行。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_ladder_pairswap
echo "=== [$(date +%T)] 表 A2（$(grep -c '|' "$EXP/configs/ladder2.txt") 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/ladder2.txt" \
  --out "$EXP/sweep_ladder2.txt" --workers 60 \
  --title "§12.177 表 A2 高阈值阶梯" | tee "$EXP/report_ladder2.txt"
echo "=== [$(date +%T)] 完成 ==="
