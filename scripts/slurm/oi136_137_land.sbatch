#!/bin/bash
#SBATCH -J rk_o136l
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 01:30:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err

# v4.132 落地（OI-136／137）：生产常量与 sweep BASE 已改为 --max-corr 1.0 / --gain-sell 1.10 ungated / --swap-margin 0.15。
# 本作业：换仓边际标度漂移守卫 ＋ 新基准两遍 14 起点重扫（在册读数重登、剔除集 A 复核）。规则臂不改逐日状态，不重建生产链。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
EXP=data/processed/experiments/exp_oi136_137

echo "=== [$(date +%T)] 换仓边际标度漂移守卫（MARGIN 0.15）==="
python3 scripts/check_swap_margin_scale_drift.py || echo "（守卫非零：V 标度已变，须按 --baseline 现值重定基准）"

echo "=== [$(date +%T)] 新基准两遍 14 起点重扫 ==="
printf '# v4.133 落地后基准核对（OI-136／137，边际 0.15）\nBASE|\n' > "$EXP/configs/base_only.txt"
python3 scripts/sweep_backtest_configs.py "$EXP/configs/base_only.txt" \
  --out "$EXP/sweep_newbase_m015.txt" --workers 28 \
  --title "v4.133 落地后基准（相关性不过滤＋涨幅减持 1.10 ungated＋换仓边际 0.15）" | tee "$EXP/report_newbase_m015.txt"
echo "=== [$(date +%T)] 完成 ==="
