#!/bin/bash
# 一条命令跑完备用策略清单（docs/Ashare_strategy_shortlist.md）：
#   bash scripts/slurm/submit_strategy_shortlist.sh
# 先为清单里「需重建」且尚未落盘的臂各提交一个建带作业，再以 afterok 依赖提交扫描作业。
# 重跑某臂的建带：删掉 $EXP/val/<臂>/align_buy_line.txt 再执行。EXP 可用环境变量覆盖。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export EXP="${EXP:-data/processed/experiments/exp_strategy_shortlist}"
deps=""
while IFS=$'\t' read -r arm extra divs panel; do
  if [ -f "$EXP/val/$arm/align_buy_line.txt" ]; then
    echo "跳过 $arm（$EXP/val/$arm 已建）"; continue
  fi
  jid=$(sbatch --parsable --job-name="rk_slval_$arm" scripts/slurm/strategy_shortlist_val_arm.sbatch "$arm" "$extra" "$divs" "$panel")
  deps+=":$jid"; echo "$arm → 作业 $jid（$extra ｜ divspread $divs ｜ $panel）"
done < <(python3 scripts/experimental/make_shortlist_configs.py --exp "$EXP" --list-builds)
if [ -n "$deps" ]; then
  sbatch --dependency="afterok$deps" scripts/slurm/strategy_shortlist.sbatch
else
  sbatch scripts/slurm/strategy_shortlist.sbatch
fi
