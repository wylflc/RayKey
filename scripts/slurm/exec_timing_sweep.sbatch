#!/bin/bash
#SBATCH -J rk_exectime
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 执行时点四臂对照（T 日收盘／T+1 开盘／T+1 开盘卖收盘买／T+1 收盘）：14 起点两遍扫描。用法：
#   sbatch scripts/slurm/exec_timing_sweep.sbatch
# 配置 data/experiments/exp_exec_timing/configs/timing.txt，出 sweep_timing.txt 与 report_timing.txt。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_exec_timing
echo "=== [$(date +%T)] timing.txt：$(grep -c '|' "$EXP/configs/timing.txt") 臂 × 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/timing.txt" --out "$EXP/sweep_timing.txt" --workers 56 \
  --title "执行时点四臂对照·timing" | tee "$EXP/report_timing.txt"
echo "=== [$(date +%T)] 完成；ERR/EMPTY 行数：$(grep -c 'ERR\|EMPTY' "$EXP/sweep_timing.txt" || true) ==="
