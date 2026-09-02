#!/bin/bash
#SBATCH -J rk_ladpair
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.177：表 A 阶梯涨幅减持（--gain-ladder，44 臂）与表 B 配对换仓（--swap-mode pairwise，15 臂），
# 各 14 起点两遍（全样本＋去赢家）。两表串行——BASE 臂的 summary 文件名相同，不可并行跑两份扫描。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_ladder_pairswap
for a in ladder pairswap; do
  echo "=== [$(date +%T)] 表 $a（$(grep -c '|' "$EXP/configs/$a.txt") 臂 × 14 起点 × 两遍）==="
  python3 scripts/sweep_backtest_configs.py "$EXP/configs/$a.txt" \
    --out "$EXP/sweep_$a.txt" --workers 60 \
    --title "§12.177 表 $a" | tee "$EXP/report_$a.txt"
done
echo "=== [$(date +%T)] 完成 ==="
