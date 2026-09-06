#!/bin/bash
#SBATCH -J rk_vol1
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 成交量触发条件·第一阶段粗扫（轨道 B，回测日志 §12.204）：27 臂 × 14 起点 × 两遍（全样本＋剔除集 A）。用法：
#   sbatch scripts/slurm/volume_trigger_stage1.sbatch
# 单次回测约 2.5 分钟、1.5 GB；56 并发 ≈ 14 波 ≈ 35 分钟，84 GB < 64 核 × 1792 MiB。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_volume_trigger
python3 scripts/test_volume_gate.py
echo "=== [$(date +%T)] 第一阶段：$(grep -c '|' "$EXP/configs/vol_stage1.txt") 臂 × 14 起点 × 两遍 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/vol_stage1.txt" --out "$EXP/sweep_stage1.txt" --workers 56 \
  --title "成交量触发条件·第一阶段（量比 20 日，建仓／加仓／换仓源／止损）" | tee "$EXP/report_stage1.txt"
echo "ERR/EMPTY 行数：$(grep -c 'ERR\|EMPTY' "$EXP/sweep_stage1.txt" || true)"
echo "=== [$(date +%T)] 完成 ==="
