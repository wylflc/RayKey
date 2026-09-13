#!/bin/bash
#SBATCH -J a_nocredit9
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 02:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 A 股对照臂：BASE 与 --credit-ratio 0，与美股同历的 9 个半年起点（2012-05 ~ 2016-05），两遍（全样本＋去赢家 A）
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
OUT=data/experiments/exp_us_sp500_port/scan_a_nocredit_9.txt
STARTS=2012-05-01,2012-11-01,2013-05-01,2013-11-01,2014-05-01,2014-11-01,2015-05-01,2015-11-01,2016-05-01
python3 scripts/sweep_backtest_configs.py data/experiments/exp_us_sp500_port/configs_a_nocredit.txt --out "$OUT" --workers 16 --starts "$STARTS" --title "OI-159 A 股无融资对照（9 起点）"
python3 scripts/sweep_backtest_configs.py --report --out "$OUT" --starts "$STARTS" --title "OI-159 A 股无融资对照（9 起点）" > "${OUT%.txt}_report.txt"
