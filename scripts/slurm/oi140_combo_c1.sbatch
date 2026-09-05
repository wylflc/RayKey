#!/bin/bash
#SBATCH -J rk_combo_c1
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.174：OI-140 C1 组合臂（8 臂 × 14 起点 × 两遍）＋ OI-135 C2 GE_TROUGHOFF 剔除集 A/B/U。
# C2 依赖 C1 先落 GE_TROUGHOFF 单臂的 summary（镜像集 B 从它读前五赢家），故串行。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_reaudit_minority

echo "=== [$(date +%T)] 表 N：三条候选的组合臂 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/combo_c1.txt" \
  --out "$EXP/sweep_combo.txt" --workers 60 \
  --title "§12.174 表 N GE_TROUGHOFF／C088／G110U 的两两与三者组合" | tee "$EXP/report_combo.txt"

echo "=== [$(date +%T)] 表 O：GE_TROUGHOFF 剔除集 A/B/U ==="
python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/u_troughoff.txt" \
  --challenger GE_TROUGHOFF --out "$EXP/sweep_u_GE_TROUGHOFF.txt" --workers 60 | tee "$EXP/report_u_GE_TROUGHOFF.txt"
echo "=== [$(date +%T)] 完成 ==="
