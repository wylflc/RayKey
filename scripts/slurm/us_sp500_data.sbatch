#!/bin/bash
#SBATCH -J us_sp500_data
#SBATCH -p rome
#SBATCH -n 16
#SBATCH -t 08:00:00
#SBATCH -o logs/%x_%j.out
#SBATCH -e logs/%x_%j.err
# OI-159 P1 数据层：利率 → companyfacts → 价格（Yahoo 段约 10 分钟，Tiingo 段按 50 请求/小时约 3~4 小时）
# 用法：sbatch scripts/slurm/us_sp500_data.sbatch [fetch_us_ohlcv_history.py 的参数，如 --phase yahoo --only AAPL,META]

cd /gpfs/work1/0/qt15419/zwang/mm_quant/RayKey
set -o pipefail
python3 scripts/fetch_us_rates.py || exit 1
python3 scripts/fetch_us_companyfacts.py || echo "companyfacts 有失败项（见 stderr），继续"
python3 scripts/fetch_us_ohlcv_history.py "$@"
