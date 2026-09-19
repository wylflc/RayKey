#!/bin/bash
#SBATCH -J a_nocredit
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 05:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 A 股对照臂：BASE 与 --credit-ratio 0，14 个标准起点，两遍（全样本＋去赢家 A）
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
OUT=data/experiments/exp_us_sp500_port/scan_a_nocredit.txt
python3 scripts/sweep_backtest_configs.py data/experiments/exp_us_sp500_port/configs_a_nocredit.txt --out "$OUT" --workers 16 --title "OI-159 A 股无融资对照"
python3 scripts/sweep_backtest_configs.py --report --out "$OUT" --title "OI-159 A 股无融资对照" > "${OUT%.txt}_report.txt"
