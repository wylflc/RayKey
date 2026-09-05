#!/bin/bash
#SBATCH -J rk_o136d
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.174 表 T：剔除赢家只数 1／3／5／10 的剂量曲线（§12.1 第 4 款②），C100／G110U／组合 对同剔除集 BASE。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi136_137
TR=$(ls data/experiments/exp_reaudit_minority/why/BASE/*_trades.csv | head -1)
python3 scripts/experimental/ex_winner_dose.py "$EXP/configs/dose_arms.txt" --trades "$TR" \
  --out "$EXP/sweep_dose.txt" --workers 60
for a in C100 G110U C100_G110U; do
  echo "--- $a"
  python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_dose.txt" --challenger "$a"
done | tee "$EXP/report_dose.txt"
echo "=== [$(date +%T)] 完成 ==="
