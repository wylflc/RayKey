#!/bin/bash
# OI-141 C12／C13／C14 一条命令跑完：先为需重建的臂各提交一个建带作业，再以 afterok 依赖提交扫描作业。
set -euo pipefail
cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
export EXP=data/experiments/exp_oi141
deps=""
while IFS=$'\t' read -r arm extra divs panel; do
  if [ -f "$EXP/val/$arm/align_buy_line.txt" ]; then echo "跳过 $arm（已建）"; continue; fi
  jid=$(sbatch --parsable --export=ALL,EXP="$EXP" --job-name="rk_o141v_$arm" scripts/slurm/strategy_shortlist_val_arm.sbatch "$arm" "$extra" "$divs" "$panel")
  deps+=":$jid"; echo "$arm → 作业 $jid（$extra ｜ divspread $divs ｜ $panel）"
done < <(python3 scripts/experimental/make_shortlist_configs.py --exp "$EXP" --list-builds)
if [ -n "$deps" ]; then sbatch --export=ALL,EXP="$EXP" --dependency="afterok$deps" scripts/slurm/oi141_coverage.sbatch
else sbatch --export=ALL,EXP="$EXP" scripts/slurm/oi141_coverage.sbatch; fi
