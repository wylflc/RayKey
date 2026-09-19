#!/bin/bash
#SBATCH -J us_sp500_sweep
#SBATCH -p rome
#SBATCH -n 32
#SBATCH -t 06:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 P4：美股臂扫描（9 起点 × 臂数 × 两遍）。用法：sbatch scripts/slurm/us_sp500_sweep.sbatch <配置文件> <结果文件> [--market us]
cd /gpfs/scratch1/shared/zwang/mm_quant/RayKey
CFG=${1:-data/experiments/exp_us_sp500_port/configs_us.txt}
OUT=${2:-data/experiments/exp_us_sp500_port/scan_us.txt}
MARKET=${3:---market us}
python3 scripts/sweep_backtest_configs.py "$CFG" --out "$OUT" $MARKET --workers 16 --title "OI-159 美股标普500历史成分（现金账户）"
python3 scripts/sweep_backtest_configs.py --report --out "$OUT" --title "OI-159 美股标普500历史成分（现金账户）" > "${OUT%.txt}_report.txt"
