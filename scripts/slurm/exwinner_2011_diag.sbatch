#!/bin/bash
#SBATCH -J rk_exw11
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 去赢家诊断：2011-11-01 起点、剔除集 A（688516/000933/002128/601328/600919）下 v4.135 与 v4.134 两臂长跑，
# 落 periods（逐年收益）与 trades，用于核对全样本与去赢家逐年差异落在哪些年份。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_swap_variants
OUT=$EXP/bt2011_exA
mkdir -p "$OUT"
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
EXA=688516,000933,002128,601328,600919
echo "=== [$(date +%T)] 开始 ==="
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --artifacts --out-dir "$OUT" --label-suffix _exA_base \
  --exclude-codes "$EXA" > "$OUT/diag_exA_base_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --swap-source-block -1 --since 2011-11-01 --artifacts --out-dir "$OUT" --label-suffix _exA_v4134 \
  --exclude-codes "$EXA" > "$OUT/diag_exA_v4134_2011.txt" 2>&1 &
wait
echo "=== [$(date +%T)] 完成 ==="
