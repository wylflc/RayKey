#!/bin/bash
#SBATCH -J rk_blsd
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.178：表 A 买入线直接剂量扫描（19 臂）与表 B 换仓机制变体（22 臂），各 14 起点两遍（全样本＋去赢家）。
# 两表串行——BASE 臂的 summary 文件名相同，不可并行跑两份扫描。末尾另跑 2011-11-01 单起点 BASE／SPT015 的成交流水，供换仓资金去向诊断。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_buyline_swapdir
for a in buyline swapdir; do
  echo "=== [$(date +%T)] 表 $a（$(grep -c '|' "$EXP/configs/$a.txt") 臂 × 14 起点 × 两遍）==="
  python3 scripts/sweep_backtest_configs.py "$EXP/configs/$a.txt" \
    --out "$EXP/sweep_$a.txt" --workers 60 \
    --title "§12.178 表 $a" | tee "$EXP/report_$a.txt"
done
echo "=== [$(date +%T)] 单起点流水诊断（2011-11-01）==="
BASE=$(python3 -c "import sys; sys.path.insert(0,'scripts'); import sweep_backtest_configs as s; print(s.BASE)")
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag178_base \
  --trade-log "$EXP/trades_base_2011.csv" --candidate-log "$EXP/cands_base_2011.csv" > "$EXP/diag_base_2011.txt" 2>&1 &
python3 scripts/backtest_valuation_strategy.py $BASE --since 2011-11-01 --label-suffix _diag178_spt \
  --swap-proceeds target --trade-log "$EXP/trades_spt_2011.csv" --candidate-log "$EXP/cands_spt_2011.csv" > "$EXP/diag_spt_2011.txt" 2>&1 &
wait
echo "=== [$(date +%T)] 完成 ==="
