#!/bin/bash
#SBATCH -J rk_shortlist
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 04:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 备用策略清单的两份扫描（docs/Ashare_strategy_shortlist.md）：先由清单生成配置，再跑规则臂与估值／宇宙臂，各出对照表。
# 需重建的臂须已由 submit_strategy_shortlist.sh 建好（本作业以 afterok 依赖它们）。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP="${EXP:-data/processed/experiments/exp_strategy_shortlist}"
TAG="$(date +%Y%m%d)"

python3 scripts/experimental/make_shortlist_configs.py --exp "$EXP"

echo "=== [$(date +%T)] 规则臂 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/shortlist_rules.txt" \
  --out "$EXP/sweep_rules_$TAG.txt" --workers 60 \
  --title "备用策略清单·规则臂（$TAG）" | tee "$EXP/report_rules_$TAG.txt"

echo "=== [$(date +%T)] 估值／宇宙臂 ==="
python3 scripts/sweep_backtest_configs.py "$EXP/configs/shortlist_val.txt" \
  --out "$EXP/sweep_val_$TAG.txt" --workers 60 \
  --title "备用策略清单·估值／宇宙臂（$TAG）" | tee "$EXP/report_val_$TAG.txt"
echo "=== [$(date +%T)] 完成 ==="
