#!/bin/bash
#SBATCH -J rk_refup
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# §12.171 表 H（单点峰补剂量）／表 J（GUARDEFF 口径换仓边际重扫）／表 I（剔除集对称性 A/B/U）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_reaudit_minority

echo "=== [$(date +%T)] 表 H：单点峰补剂量（16 臂）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/single_point_dose.txt" \
  --out "$EXP/sweep_dose.txt" --workers 60 \
  --title "§12.171 表 H 上移锚／卖侧容差／涨幅加仓上限的剂量" | tee "$EXP/report_dose.txt"

echo "=== [$(date +%T)] 表 J：GUARDEFF 口径换仓边际重扫（11 臂）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/guardeff_margin.txt" \
  --out "$EXP/sweep_gemargin.txt" --workers 60 \
  --title "§12.171 表 J GUARDEFF 口径上的换仓边际（对照＝该口径 × 0.18）" | tee "$EXP/report_gemargin.txt"

echo "=== [$(date +%T)] 表 I：剔除集对称性 A/B/U ==="
for c in GUARDEFF:u_guardeff C088:u_corr G110U:u_gain; do
  arm=${c%%:*}; cfg=${c##*:}
  echo "--- $arm ---"
  python3 scripts/experimental/ex_winner_symmetry.py "$EXP/configs/$cfg.txt" \
    --challenger "$arm" --out "$EXP/sweep_u_$arm.txt" --workers 60 | tee "$EXP/report_u_$arm.txt"
done
echo "=== [$(date +%T)] 完成 ==="
