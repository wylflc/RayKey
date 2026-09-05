#!/bin/bash
#SBATCH -J rk_sb1pf
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.179 后续：SB1 候选臂的 K 剂量 ＋ 换仓边际 0.01 一档重扫（20 臂 × 14 起点两遍），随后剔除集对称性 A/B/U（ex_winner_symmetry.py）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_swap_variants
echo "=== [$(date +%T)] sb1_platform（$(grep -c '|' "$EXP/configs/sb1_platform.txt") 臂 × 14 起点 × 两遍）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/sb1_platform.txt" \
  --out "$EXP/sweep_sb1_platform.txt" --workers 60 \
  --title "§12.179 SB1 平台检验" | tee "$EXP/report_sb1_platform.txt"
echo "=== [$(date +%T)] 剔除集对称性 A/B/U（挑战臂 SB1）==="
python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/sb1_sym.txt" --challenger SB1 \
  --out "$EXP/sweep_sb1_sym.txt" --workers 60 2>&1 | tail -8
python3 scripts/experimental/ex_winner_symmetry_report.py "$EXP/sweep_sb1_sym.txt" --challenger SB1 \
  > "$EXP/report_sb1_sym.txt" 2>&1 || echo "（sym report 非零退出）"
echo "=== [$(date +%T)] 完成 ==="
