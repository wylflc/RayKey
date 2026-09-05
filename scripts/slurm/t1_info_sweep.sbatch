#!/bin/bash
#SBATCH -J rk_t1info
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# T+1 信息依赖审核：止损时点三口径 ＋ 其他操作零延迟（--t1-judge）＋ T+1 确认两臂，14 起点两遍。用法：
#   sbatch scripts/slurm/t1_info_sweep.sbatch
# 配置 data/experiments/exp_t1_info/configs/t1.txt，出 sweep_t1.txt 与 report_t1.txt。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_t1_info
echo "=== [$(date +%T)] t1.txt：$(grep -c '|' "$EXP/configs/t1.txt") 臂 × 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/t1.txt" --out "$EXP/sweep_t1.txt" --workers 56 \
  --title "T+1 信息依赖审核·t1" | tee "$EXP/report_t1.txt"
echo "=== [$(date +%T)] 完成；ERR/EMPTY 行数：$(grep -c 'ERR\|EMPTY' "$EXP/sweep_t1.txt" || true) ==="
