#!/bin/bash
#SBATCH -J rk_whipsaw
#SBATCH -p rome
#SBATCH -n 64
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 换仓卖出源弱势形态复核：14 起点两遍扫描。用法：
#   sbatch --export=ALL,CFGS="round2.txt trunc2024.txt" scripts/slurm/whipsaw_swap_sweep.sbatch
# 每个配置文件 <name>.txt 出 sweep_<name>.txt 与 report_<name>.txt（data/experiments/exp_whipsaw_swap/）。
set -euo pipefail
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
EXP=data/experiments/exp_whipsaw_swap
for cfg in ${CFGS:-round2.txt}; do
  name="${cfg%.txt}"
  echo "=== [$(date +%T)] $cfg：$(grep -c '|' "$EXP/configs/$cfg") 臂 × 14 起点 × 两遍 ==="
  python3 scripts/sweep_backtest_configs.py "$EXP/configs/$cfg" --out "$EXP/sweep_$name.txt" --workers 60 \
    --title "换仓弱势形态复核·$name" | tee "$EXP/report_$name.txt"
done
echo "=== [$(date +%T)] 完成 ==="
