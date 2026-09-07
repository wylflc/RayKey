#!/bin/bash
# 一条命令跑完备用策略清单（docs/reports/Ashare_strategy_shortlist.md）：
#   bash scripts/slurm/submit_strategy_shortlist.sh
# 先为清单里「需重建」且尚未落盘的臂各提交一个建带作业，再以 afterok 依赖提交扫描作业。
# 状态文件已清理时自动重建；强制重跑某臂可删掉其 align_buy_line.txt。EXP 可用环境变量覆盖。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export EXP="${EXP:-data/experiments/exp_strategy_shortlist}"
deps=""
while IFS=$'\t' read -r arm extra divs panel; do
  jid=$(sbatch --parsable --export=ALL,EXP="$EXP" --job-name="rk_slval_$arm" scripts/slurm/strategy_shortlist_val_arm.sbatch "$arm" "$extra" "$divs" "$panel")
  deps+=":$jid"; echo "$arm → 作业 $jid（$extra ｜ divspread $divs ｜ $panel）"
done < <(python3 scripts/experimental/make_shortlist_configs.py --exp "$EXP" --list-builds --missing-only)
if [ -n "$deps" ]; then
  sbatch --export=ALL,EXP="$EXP" --dependency="afterok$deps" scripts/slurm/strategy_shortlist.sbatch
else
  sbatch --export=ALL,EXP="$EXP" scripts/slurm/strategy_shortlist.sbatch
fi
