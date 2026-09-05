#!/bin/bash
#SBATCH -J rk_ss14reg
#SBATCH -p rome
#SBATCH -n 48
#SBATCH -t 00:45:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# 起点集改 ≥10 年 14 个后的 `BASE` 在册读数重登（§12.158 裁定落地，v4.117）。
# 标准链：sweep_backtest_configs.py 全市场状态文件 + 现行两线，BASE 单臂，
# 全样本 + 去赢家两遍 = 28 次运行 × ~1.5 分钟；--workers 24 ≈ 36 GB < -n 48 的 84 GB。
# 读数落 §12.1 在册行与回测日志 §12.160。

set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey

EXP=data/experiments/exp_startset14
mkdir -p "$EXP/configs"
printf 'BASE|\n' > "$EXP/configs/base.txt"

python3 scripts/sweep_backtest_configs.py "$EXP/configs/base.txt" \
  --out "$EXP/sweep_base14.txt" \
  --workers 24 \
  --title "起点集 ≥10 年 14 起点在册重登（v4.117）" \
  | tee "$EXP/report_base14.txt"

echo "=== [$(date +%H:%M:%S)] 完成 ==="
