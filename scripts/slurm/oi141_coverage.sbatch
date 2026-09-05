#!/bin/bash
#SBATCH -J rk_oi141
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 03:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# OI-141 待跑 C12（宇宙 v6a）／C13（divspread 剂量）／C14（四个在册参数剂量）：
# 清单 data/experiments/exp_oi141/configs/shortlist_arms.tsv，建带臂须已由 submit_oi141_coverage.sh 建好（afterok）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/experiments/exp_oi141
python3 scripts/experimental/make_shortlist_configs.py --exp "$EXP"

echo "=== [$(date +%T)] C14 参数剂量臂 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/shortlist_rules.txt" \
  --out "$EXP/sweep_c14_params.txt" --workers 60 \
  --title "OI-141 C14 在册参数剂量：--max-positions／--scan-depth／--corr-window／--trend-ma" | tee "$EXP/report_c14_params.txt"

echo "=== [$(date +%T)] C12／C13 宇宙与 divspread 剂量臂（买入线各自重解）==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/shortlist_val.txt" \
  --out "$EXP/sweep_c12_c13_val.txt" --workers 60 \
  --title "OI-141 C12 宇宙 v6a／C13 divspread 0.01~0.03（买入线按 §12.30 重解）" | tee "$EXP/report_c12_c13_val.txt"
echo "=== [$(date +%T)] 完成 ==="
